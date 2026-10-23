"""settings.py — environment detection, production safety checks, quota defaults."""
from __future__ import annotations

import dataclasses
import logging

import pytest

import settings
from settings import QUOTA_FEATURES, get_settings

DEV_SECRET = settings._DEV_JWT_SECRET


@pytest.fixture
def clean_env(monkeypatch):
    """Strip every variable settings.py reads so each test controls its own inputs."""
    for name in (
        "ENV", "K_SERVICE", "JWT_SECRET", "JWT_ISSUER", "ACCESS_TOKEN_MINUTES",
        "REFRESH_TOKEN_DAYS", "OPENAI_CHAT_MODEL", "OPENAI_VISION_MODEL",
        "OPENAI_VISION_DETAIL", "GEMINI_MODELS", "CORS_ORIGINS", "MAX_UPLOAD_BYTES",
        "MAX_IMAGE_PIXELS", "TRUSTED_PROXY_HOPS", "MAX_WARDROBE_ITEMS", "CHAT_WARDROBE_LIMIT",
        "GLOBAL_DAILY_AI_CALLS",
        *[f"QUOTA_FREE_{f.upper()}_MONTHLY" for f in QUOTA_FEATURES],
    ):
        monkeypatch.delenv(name, raising=False)
    settings.reset_settings_cache()
    return monkeypatch


def fresh(monkeypatch, **env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    settings.reset_settings_cache()
    return get_settings()


# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------

class TestEnvDetection:
    @pytest.mark.parametrize("value", ["dev", "test", "prod"])
    def test_explicit_env_var_is_used(self, clean_env, value):
        assert fresh(clean_env, ENV=value).env == value

    def test_env_var_is_case_and_whitespace_insensitive(self, clean_env):
        assert fresh(clean_env, ENV="  PROD ").env == "prod"

    def test_defaults_to_dev_without_any_hint(self, clean_env):
        assert fresh(clean_env).env == "dev"

    def test_k_service_means_production(self, clean_env):
        assert fresh(clean_env, K_SERVICE="closetmate-api").env == "prod"

    @pytest.mark.parametrize("explicit", ["dev", "test"])
    def test_k_service_beats_a_stray_env_override(self, clean_env, explicit):
        """A deployed Cloud Run service is ALWAYS production, whatever ENV says."""
        assert fresh(clean_env, K_SERVICE="closetmate-api", ENV=explicit).env == "prod"

    @pytest.mark.parametrize("alias,expected", [("production", "prod"), ("Production", "prod"), ("development", "dev")])
    def test_long_form_aliases_are_accepted(self, clean_env, alias, expected):
        assert fresh(clean_env, ENV=alias).env == expected

    @pytest.mark.parametrize("typo", ["live", "staging", "prd", "prod!", "prodution", "1"])
    def test_unrecognised_env_raises_instead_of_silently_becoming_dev(self, clean_env, typo):
        clean_env.setenv("ENV", typo)
        settings.reset_settings_cache()
        with pytest.raises(RuntimeError, match="ENV"):
            get_settings()

    def test_blank_env_is_dev(self, clean_env):
        assert fresh(clean_env, ENV="   ").env == "dev"

    def test_k_service_wins_even_over_an_unrecognised_env(self, clean_env):
        assert fresh(clean_env, ENV="live", K_SERVICE="svc").env == "prod"

    def test_empty_k_service_is_not_production(self, clean_env):
        assert fresh(clean_env, K_SERVICE="").env == "dev"

    def test_is_prod_and_expose_error_details_follow_env(self, clean_env):
        prod = fresh(clean_env, ENV="prod")
        assert prod.is_prod and not prod.expose_error_details
        clean_env.setenv("ENV", "dev")
        settings.reset_settings_cache()
        dev = get_settings()
        assert not dev.is_prod and dev.expose_error_details


# ---------------------------------------------------------------------------
# validate_for_runtime
# ---------------------------------------------------------------------------

class TestValidateForRuntime:
    def test_prod_without_jwt_secret_refuses_to_boot(self, clean_env):
        s = fresh(clean_env, ENV="prod")
        assert s.jwt_secret == DEV_SECRET
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            s.validate_for_runtime()

    def test_prod_with_blank_jwt_secret_is_treated_as_missing(self, clean_env):
        with pytest.raises(RuntimeError):
            fresh(clean_env, ENV="prod", JWT_SECRET="   ").validate_for_runtime()

    def test_prod_with_short_jwt_secret_refuses_to_boot(self, clean_env):
        with pytest.raises(RuntimeError, match="32"):
            fresh(clean_env, ENV="prod", JWT_SECRET="x" * 31).validate_for_runtime()

    def test_prod_with_the_published_dev_secret_refuses_to_boot(self, clean_env):
        with pytest.raises(RuntimeError):
            fresh(clean_env, ENV="prod", JWT_SECRET=DEV_SECRET).validate_for_runtime()

    def test_prod_with_32_char_secret_boots(self, clean_env):
        fresh(clean_env, ENV="prod", JWT_SECRET="x" * 32).validate_for_runtime()

    def test_k_service_alone_triggers_the_prod_check(self, clean_env):
        with pytest.raises(RuntimeError):
            fresh(clean_env, K_SERVICE="svc").validate_for_runtime()

    def test_dev_with_the_published_dev_secret_only_warns(self, clean_env, caplog):
        s = fresh(clean_env, ENV="dev", JWT_SECRET=DEV_SECRET)
        with caplog.at_level(logging.WARNING, logger="settings"):
            s.validate_for_runtime()
        assert "dev JWT secret" in caplog.text

    def test_dev_without_a_secret_gets_a_random_per_process_secret(self, clean_env):
        first = fresh(clean_env, ENV="dev").jwt_secret
        settings.reset_settings_cache()
        second = get_settings().jwt_secret
        assert first != DEV_SECRET and second != DEV_SECRET
        assert len(first) >= 32 and first != second
        fresh(clean_env, ENV="dev").validate_for_runtime()      # and that is not even worth a warning

    def test_dev_with_real_secret_is_silent(self, clean_env, caplog):
        s = fresh(clean_env, ENV="dev", JWT_SECRET="y" * 40)
        with caplog.at_level(logging.WARNING, logger="settings"):
            s.validate_for_runtime()
        assert caplog.text == ""

    def test_error_message_never_contains_the_secret(self, clean_env):
        s = fresh(clean_env, ENV="prod", JWT_SECRET="shortsecret")
        with pytest.raises(RuntimeError) as exc:
            s.validate_for_runtime()
        assert "shortsecret" not in str(exc.value)


# ---------------------------------------------------------------------------
# Quota defaults and overrides
# ---------------------------------------------------------------------------

class TestQuotaDefaults:
    def test_prod_defaults_are_strict(self, clean_env):
        s = fresh(clean_env, ENV="prod")
        assert s.quota_free == {"chat": 60, "vision": 40, "bgremove": 80, "insights": 4}

    @pytest.mark.parametrize("env", ["dev", "test"])
    def test_non_prod_defaults_are_lenient(self, clean_env, env):
        s = fresh(clean_env, ENV=env)
        assert set(s.quota_free) == set(QUOTA_FEATURES)
        assert all(limit == 100_000 for limit in s.quota_free.values())

    def test_env_var_overrides_a_single_feature(self, clean_env):
        s = fresh(clean_env, ENV="prod", QUOTA_FREE_CHAT_MONTHLY="7")
        assert s.quota_limit("chat") == 7
        assert s.quota_limit("vision") == 40

    def test_non_numeric_override_falls_back_to_default(self, clean_env, caplog):
        with caplog.at_level(logging.WARNING, logger="settings"):
            s = fresh(clean_env, ENV="prod", QUOTA_FREE_CHAT_MONTHLY="lots")
        assert s.quota_limit("chat") == 60
        assert "QUOTA_FREE_CHAT_MONTHLY" in caplog.text

    def test_blank_override_falls_back_to_default(self, clean_env):
        assert fresh(clean_env, ENV="prod", QUOTA_FREE_VISION_MONTHLY="  ").quota_limit("vision") == 40

    def test_unknown_feature_has_zero_limit(self, clean_env):
        assert fresh(clean_env).quota_limit("teleportation") == 0

    def test_zero_override_is_respected(self, clean_env):
        assert fresh(clean_env, QUOTA_FREE_CHAT_MONTHLY="0").quota_limit("chat") == 0


# ---------------------------------------------------------------------------
# Remaining fields
# ---------------------------------------------------------------------------

class TestOtherSettings:
    def test_defaults(self, clean_env):
        s = fresh(clean_env)
        assert s.jwt_issuer == "closetmate"
        assert s.access_token_minutes == 15
        assert s.refresh_token_days == 60
        assert s.max_upload_bytes == 12 * 1024 * 1024
        assert s.max_image_pixels == 36_000_000
        assert s.max_wardrobe_items == 500
        assert s.chat_wardrobe_limit == 200
        assert s.trusted_proxy_hops == 0
        assert s.global_daily_ai_calls == 0
        assert s.openai_chat_model == "gpt-4o-mini"
        assert s.gemini_models == ("gemini-2.5-flash", "gemini-2.5-flash-lite")
        assert s.openai_vision_detail == "high"

    def test_global_daily_ai_budget_defaults_on_in_prod_only(self, clean_env):
        assert fresh(clean_env, ENV="prod").global_daily_ai_calls == 20_000
        assert fresh(clean_env, ENV="dev").global_daily_ai_calls == 0
        assert fresh(clean_env, ENV="prod", GLOBAL_DAILY_AI_CALLS="5").global_daily_ai_calls == 5

    def test_trusted_proxy_hops(self, clean_env):
        assert fresh(clean_env, K_SERVICE="svc").trusted_proxy_hops == 1      # Cloud Run front end
        clean_env.setenv("TRUSTED_PROXY_HOPS", "2")
        settings.reset_settings_cache()
        assert get_settings().trusted_proxy_hops == 2

    def test_wardrobe_and_prompt_caps_are_configurable(self, clean_env):
        s = fresh(clean_env, MAX_WARDROBE_ITEMS="10", CHAT_WARDROBE_LIMIT="3")
        assert (s.max_wardrobe_items, s.chat_wardrobe_limit) == (10, 3)

    def test_cors_origins_default_by_environment(self, clean_env):
        assert fresh(clean_env, ENV="dev").cors_origins == ("*",)
        assert fresh(clean_env, ENV="prod").cors_origins == ()

    def test_cors_origins_csv_is_trimmed(self, clean_env):
        s = fresh(clean_env, ENV="prod", CORS_ORIGINS=" https://a.test , https://b.test ,, ")
        assert s.cors_origins == ("https://a.test", "https://b.test")

    def test_gemini_models_csv_preserves_order(self, clean_env):
        s = fresh(clean_env, GEMINI_MODELS="m-3,m-1,m-2")
        assert s.gemini_models == ("m-3", "m-1", "m-2")

    @pytest.mark.parametrize("raw,expected", [("LOW", "low"), ("auto", "auto"), ("ultra", "high"), ("", "high")])
    def test_vision_detail_is_validated(self, clean_env, raw, expected):
        assert fresh(clean_env, OPENAI_VISION_DETAIL=raw).openai_vision_detail == expected

    def test_get_settings_is_cached_until_reset(self, clean_env):
        first = fresh(clean_env, ACCESS_TOKEN_MINUTES="5")
        clean_env.setenv("ACCESS_TOKEN_MINUTES", "30")
        assert get_settings() is first and first.access_token_minutes == 5
        settings.reset_settings_cache()
        assert get_settings().access_token_minutes == 30

    def test_settings_are_immutable(self, clean_env):
        with pytest.raises(dataclasses.FrozenInstanceError):
            fresh(clean_env).env = "prod"  # type: ignore[misc]

    def test_get_secret_trims_and_maps_blank_to_none(self, clean_env):
        clean_env.setenv("SOME_SECRET", "  abc  ")
        clean_env.setenv("EMPTY_SECRET", "   ")
        assert settings.get_secret("SOME_SECRET") == "abc"
        assert settings.get_secret("EMPTY_SECRET") is None
        assert settings.get_secret("DOES_NOT_EXIST_ANYWHERE") is None


# ---------------------------------------------------------------------------
# .env loader
# ---------------------------------------------------------------------------

class TestLoadEnv:
    def _forget(self, monkeypatch, *names):
        # setenv-then-delenv makes monkeypatch remove the variable again at teardown,
        # even though load_env() writes to os.environ behind its back.
        for name in names:
            monkeypatch.setenv(name, "x")
            monkeypatch.delenv(name)

    def test_loads_pairs_ignoring_comments_blanks_and_quotes(self, tmp_path, monkeypatch):
        self._forget(monkeypatch, "CM_TEST_PLAIN", "CM_TEST_QUOTED", "CM_TEST_SINGLE", "CM_TEST_EQ")
        env_file = tmp_path / ".env"
        env_file.write_text(
            "# a comment\n\nCM_TEST_PLAIN=hello\nCM_TEST_QUOTED=\"two words\"\n"
            "CM_TEST_SINGLE='single'\nnot a pair\nCM_TEST_EQ=a=b=c\n",
            encoding="utf-8",
        )
        settings.load_env(env_file)
        import os

        assert os.environ["CM_TEST_PLAIN"] == "hello"
        assert os.environ["CM_TEST_QUOTED"] == "two words"
        assert os.environ["CM_TEST_SINGLE"] == "single"
        assert os.environ["CM_TEST_EQ"] == "a=b=c"

    def test_never_overwrites_an_existing_variable(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CM_TEST_KEEP", "from-real-env")
        env_file = tmp_path / ".env"
        env_file.write_text("CM_TEST_KEEP=from-file\n", encoding="utf-8")
        settings.load_env(env_file)
        import os

        assert os.environ["CM_TEST_KEEP"] == "from-real-env"

    def test_an_empty_existing_variable_also_wins(self, tmp_path, monkeypatch):
        """This is what keeps a developer's real .env keys out of the test-suite."""
        monkeypatch.setenv("CM_TEST_BLANK", "")
        env_file = tmp_path / ".env"
        env_file.write_text("CM_TEST_BLANK=secret\n", encoding="utf-8")
        settings.load_env(env_file)
        import os

        assert os.environ["CM_TEST_BLANK"] == ""

    def test_missing_file_is_not_an_error(self, tmp_path):
        settings.load_env(tmp_path / "nope.env")
