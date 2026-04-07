import {
  View,
  Text,
  Image,
  Pressable,
  ActivityIndicator,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  useColorScheme,
  Dimensions,
  TextInput,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import * as ImagePicker from "expo-image-picker";
import { useState, useEffect, useCallback } from "react";
import { useLocalSearchParams, useRouter } from "expo-router";
import { removeBackground, analyzeClothing, addWardrobeItem } from "@/src/api/ai";
import { Ionicons } from "@expo/vector-icons";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const { width } = Dimensions.get("window");
const CAPTURE_SIZE = width - 48;
const PREVIEW_SIZE = 80;
const DEMO_USER_ID = "demo_user";

// ---------------------------------------------------------------------------
// Screen
// ---------------------------------------------------------------------------

export default function AddItemScreen() {
  const params = useLocalSearchParams<{ imageUri?: string }>();
  const router = useRouter();
  const colorScheme = useColorScheme();
  const isDark = colorScheme === "dark";

  // ── Image state ───────────────────────────────────────────────────────────
  const [originalUri, setOriginalUri] = useState<string | null>(null);
  const [styledUri, setStyledUri] = useState<string | null>(null);
  const [imagePath, setImagePath] = useState<string>("");   // backend logical path

  // ── Loading states ────────────────────────────────────────────────────────
  const [removingBg, setRemovingBg] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [saving, setSaving] = useState(false);

  // ── Form fields ───────────────────────────────────────────────────────────
  const [category, setCategory] = useState("");
  const [subcategory, setSubcategory] = useState("");
  const [color, setColor] = useState("");
  const [material, setMaterial] = useState("");
  const [pattern, setPattern] = useState("");
  const [style, setStyle] = useState("");

  // ── Derived ───────────────────────────────────────────────────────────────
  const loading = removingBg || analyzing;
  const displayUri = styledUri ?? originalUri;
  const hasImage = !!originalUri;
  const canSave = !!styledUri && !saving;

  // ── Helper: analyze + remove-bg in parallel ───────────────────────────────
  const processImage = useCallback(async (uri: string) => {
    setRemovingBg(true);
    setAnalyzing(true);
    setStyledUri(null);

    // Run both calls concurrently for speed
    const [bgResult, analyzeResult] = await Promise.allSettled([
      removeBackground(uri),
      analyzeClothing(uri),
    ]);

    // Background removal
    setRemovingBg(false);
    if (bgResult.status === "fulfilled") {
      setStyledUri(bgResult.value);
    } else {
      console.error("[add-item] Background removal failed:", bgResult.reason);
      // Non-fatal — user still sees original image; show a soft warning
      Alert.alert(
        "Background removal failed",
        "The original photo will be used. You can still add the item.",
        [{ text: "OK" }]
      );
      // Use original as fallback so save button isn't permanently disabled
      setStyledUri(uri);
    }

    // Analyze / autofill
    setAnalyzing(false);
    if (analyzeResult.status === "fulfilled") {
      const { suggested, image_path } = analyzeResult.value;
      setImagePath(image_path ?? "");
      // Autofill — user can edit all fields afterwards
      if (suggested.category)      setCategory(suggested.category);
      if (suggested.subcategory)   setSubcategory(suggested.subcategory);
      if (suggested.primary_color) setColor(suggested.primary_color);
      if (suggested.material)      setMaterial(suggested.material);
      if (suggested.pattern)       setPattern(suggested.pattern);
      if (suggested.formality)     setStyle(suggested.formality);
    } else {
      console.warn("[add-item] Analyze failed, manual input allowed:", analyzeResult.reason);
      // Silent — form stays empty so user can fill manually
    }
  }, []);

  // ── On param change (from FloatingCameraButton) ───────────────────────────
  useEffect(() => {
    if (params.imageUri) {
      setOriginalUri(params.imageUri);
      setStyledUri(null);
      processImage(params.imageUri);
    }
  }, [params.imageUri, processImage]);

  // ── Camera picker ─────────────────────────────────────────────────────────
  const pickImage = async () => {
    const { status } = await ImagePicker.requestCameraPermissionsAsync();
    if (status !== "granted") {
      Alert.alert(
        "Camera permission",
        "Camera access is needed to capture clothing items.",
        [{ text: "OK" }]
      );
      return;
    }

    const result = await ImagePicker.launchCameraAsync({
      quality: 0.8,
      allowsEditing: true,
      aspect: [1, 1],
    });

    if (!result.canceled) {
      const uri = result.assets[0].uri;
      setOriginalUri(uri);
      setStyledUri(null);
      processImage(uri);
    }
  };

  const clearPreview = () => {
    setOriginalUri(null);
    setStyledUri(null);
    setImagePath("");
    setCategory("");
    setSubcategory("");
    setColor("");
    setMaterial("");
    setPattern("");
    setStyle("");
  };

  // ── Save ──────────────────────────────────────────────────────────────────
  const handleSave = async () => {
    if (!canSave) return;
    setSaving(true);
    try {
      await addWardrobeItem({
        user_id: DEMO_USER_ID,
        image_path: styledUri || originalUri || imagePath || "",
        category:     category.trim()    || "unknown",
        subcategory:  subcategory.trim() || "unknown",
        primary_color: color.trim()      || "unknown",
        material:     material.trim()    || "unknown",
        pattern:      pattern.trim()     || "solid",
        formality:    style.trim()       || "casual",
        culture:      "global",
      });
      Alert.alert("Added! ✓", "Item saved to your closet.", [
        { text: "OK", onPress: () => router.back() },
      ]);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      Alert.alert("Save failed", msg, [
        { text: "Retry", onPress: handleSave },
        { text: "Cancel", style: "cancel" },
      ]);
    } finally {
      setSaving(false);
    }
  };

  // ── Status text shown on the loading overlay ──────────────────────────────
  const loadingLabel = analyzing
    ? "Analyzing your outfit..."
    : removingBg
    ? "Removing background..."
    : "";

  const styles = createStyles(isDark);

  return (
    <SafeAreaView style={styles.safeArea}>
      <ScrollView
        contentContainerStyle={styles.scrollContent}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        {/* Top bar */}
        <View style={styles.topBar}>
          <TouchableOpacity style={styles.topIcon} hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}>
            <Ionicons name="flash-outline" size={26} color={isDark ? "#FFF" : "#000"} />
          </TouchableOpacity>
          <TouchableOpacity style={styles.topIcon} hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}>
            <Ionicons name="camera-reverse-outline" size={26} color={isDark ? "#FFF" : "#000"} />
          </TouchableOpacity>
        </View>

        {/* Capture area */}
        <View style={styles.captureWrapper}>
          <Pressable style={styles.captureArea} onPress={!hasImage ? pickImage : undefined}>
            {hasImage ? (
              <Image
                source={{ uri: displayUri ?? undefined }}
                style={styles.captureImage}
                resizeMode="contain"
              />
            ) : (
              <View style={styles.capturePlaceholder}>
                <Ionicons name="camera-outline" size={48} color={isDark ? "#666" : "#999"} />
                <Text style={styles.capturePlaceholderText}>Tap to capture</Text>
              </View>
            )}
            {loading && (
              <View style={styles.loadingOverlay}>
                <ActivityIndicator size="large" color="#FFF" />
                {!!loadingLabel && (
                  <Text style={styles.loadingLabel}>{loadingLabel}</Text>
                )}
              </View>
            )}
          </Pressable>
        </View>

        {/* Preview thumbnail */}
        {hasImage && (
          <View style={styles.previewRow}>
            <View style={styles.previewThumbWrapper}>
              <Image
                source={{ uri: displayUri ?? undefined }}
                style={styles.previewThumb}
                resizeMode="cover"
              />
              <TouchableOpacity
                style={styles.previewRemove}
                onPress={clearPreview}
                hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
              >
                <Ionicons name="close" size={20} color={isDark ? "#FFF" : "#000"} />
              </TouchableOpacity>
            </View>
          </View>
        )}

        {/* Form card */}
        <View style={styles.formCard}>
          <FormRow
            label="Category:"
            value={category}
            onChange={setCategory}
            placeholder="e.g. top"
            isDark={isDark}
            styles={styles}
          />
          <FormRow
            label="Sub-type:"
            value={subcategory}
            onChange={setSubcategory}
            placeholder="e.g. panjabi"
            isDark={isDark}
            styles={styles}
          />
          <FormRow
            label="Color:"
            value={color}
            onChange={setColor}
            placeholder="e.g. navy blue"
            isDark={isDark}
            styles={styles}
          />
          <FormRow
            label="Material:"
            value={material}
            onChange={setMaterial}
            placeholder="e.g. cotton"
            isDark={isDark}
            styles={styles}
          />
          <FormRow
            label="Pattern:"
            value={pattern}
            onChange={setPattern}
            placeholder="e.g. solid"
            isDark={isDark}
            styles={styles}
          />
          <FormRow
            label="Style:"
            value={style}
            onChange={setStyle}
            placeholder="e.g. casual"
            isDark={isDark}
            styles={styles}
            last
          />
        </View>

        {/* Confirm button */}
        <Pressable
          style={[
            styles.confirmButton,
            (!canSave || loading) && styles.confirmButtonDisabled,
          ]}
          onPress={canSave && !loading ? handleSave : undefined}
          disabled={!canSave || loading}
        >
          {saving ? (
            <ActivityIndicator color="#FFF" />
          ) : (
            <Text style={styles.confirmButtonText}>Confirm &amp; Add to Closet</Text>
          )}
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

// ---------------------------------------------------------------------------
// FormRow helper
// ---------------------------------------------------------------------------

interface FormRowProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  isDark: boolean;
  styles: ReturnType<typeof createStyles>;
  last?: boolean;
}

function FormRow({ label, value, onChange, placeholder, isDark, styles, last }: FormRowProps) {
  return (
    <View style={[styles.formRow, last && { marginBottom: 0 }]}>
      <Text style={styles.formLabel}>{label}</Text>
      <TextInput
        style={styles.formInput}
        value={value}
        onChangeText={onChange}
        placeholder={placeholder}
        placeholderTextColor={isDark ? "#636366" : "#8E8E93"}
        autoCapitalize="none"
        autoCorrect={false}
      />
    </View>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

function createStyles(isDark: boolean) {
  return StyleSheet.create({
    safeArea: {
      flex: 1,
      backgroundColor: isDark ? "#000" : "#FFF",
    },
    scrollContent: {
      paddingHorizontal: 24,
      paddingBottom: 40,
    },
    topBar: {
      flexDirection: "row",
      justifyContent: "space-between",
      alignItems: "center",
      paddingVertical: 16,
    },
    topIcon: {
      padding: 4,
    },
    captureWrapper: {
      alignItems: "center",
      marginBottom: 16,
    },
    captureArea: {
      width: CAPTURE_SIZE,
      height: CAPTURE_SIZE,
      borderRadius: 16,
      borderWidth: 2,
      borderStyle: "dashed",
      borderColor: isDark ? "#444" : "#DDD",
      overflow: "hidden",
      backgroundColor: isDark ? "#1C1C1E" : "#F2F2F7",
    },
    captureImage: {
      width: "100%",
      height: "100%",
    },
    capturePlaceholder: {
      flex: 1,
      justifyContent: "center",
      alignItems: "center",
      gap: 8,
    },
    capturePlaceholderText: {
      fontSize: 14,
      color: isDark ? "#666" : "#999",
    },
    loadingOverlay: {
      ...StyleSheet.absoluteFillObject,
      backgroundColor: "rgba(0,0,0,0.6)",
      justifyContent: "center",
      alignItems: "center",
      gap: 12,
    },
    loadingLabel: {
      color: "#FFF",
      fontSize: 14,
      fontWeight: "500",
      textAlign: "center",
    },
    previewRow: {
      flexDirection: "row",
      marginBottom: 16,
    },
    previewThumbWrapper: {
      width: PREVIEW_SIZE,
      height: PREVIEW_SIZE,
      borderRadius: 12,
      overflow: "hidden",
      backgroundColor: isDark ? "#2C2C2E" : "#E5E5EA",
    },
    previewThumb: {
      width: "100%",
      height: "100%",
    },
    previewRemove: {
      position: "absolute",
      top: 4,
      right: 4,
      width: 24,
      height: 24,
      borderRadius: 12,
      backgroundColor: "rgba(0,0,0,0.5)",
      justifyContent: "center",
      alignItems: "center",
    },
    formCard: {
      backgroundColor: isDark ? "#1C1C1E" : "#FFFFFF",
      borderRadius: 16,
      padding: 16,
      marginBottom: 24,
      borderWidth: isDark ? 0 : 1,
      borderColor: "#E5E5EA",
    },
    formRow: {
      flexDirection: "row",
      alignItems: "center",
      marginBottom: 12,
    },
    formLabel: {
      fontSize: 14,
      color: isDark ? "#AEAEB2" : "#3C3C43",
      width: 80,
    },
    formInput: {
      flex: 1,
      fontSize: 15,
      color: isDark ? "#FFF" : "#000",
      paddingVertical: 6,
      paddingHorizontal: 0,
      borderBottomWidth: StyleSheet.hairlineWidth,
      borderBottomColor: isDark ? "#444" : "#E5E5EA",
    },
    confirmButton: {
      backgroundColor: "#FF6347",
      borderRadius: 12,
      paddingVertical: 16,
      alignItems: "center",
      justifyContent: "center",
    },
    confirmButtonDisabled: {
      opacity: 0.5,
    },
    confirmButtonText: {
      fontSize: 16,
      fontWeight: "600",
      color: "#FFFFFF",
    },
  });
}
