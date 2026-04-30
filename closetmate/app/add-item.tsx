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
import { useState, useEffect } from "react";
import { useLocalSearchParams, useRouter } from "expo-router";
import { removeBackground, analyzeClothing, addWardrobeItem } from "@/src/api/ai";
import * as FileSystem from "expo-file-system/legacy";
import { Ionicons } from "@expo/vector-icons";
import { useAuth } from "@/src/context/AuthContext";

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
  const { user_id } = useAuth();
  const activeUserId = user_id ?? 'demo_user';

  // ── Image state ───────────────────────────────────────────────────────────
  const [originalUri, setOriginalUri] = useState<string | null>(null);
  const [previewUri, setPreviewUri] = useState<string | null>(null);    // displayable URI (local or data:)
  // persistentImagePath stores the final image that goes into the DB:
  //   - a base64 data URI (from /remove-bg)  → works offline, no server needed
  //   - falls back to the original local URI if remove-bg fails
  const [persistentImagePath, setPersistentImagePath] = useState<string>("");
  const [imagePath, setImagePath] = useState<string>("");              // from analyze (server-relative path, NOT used for image display)

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
  const displayUri = previewUri ?? originalUri;
  const hasImage = !!originalUri;
  // Can save as long as we have any persistent image path (data URI or local URI)
  const canSave = !!persistentImagePath && !saving;

  // ── Persistent image storage — document directory (survives restarts) ───
  //
  // The app's documentDirectory is permanent storage that React Native can
  // read as a file:// URI with no size or memory issues — unlike base64 data
  // URIs which silently fail to render when they exceed ~1–2 MB.
  //
  const IMG_DIR = `${FileSystem.documentDirectory}closetmate_images/`;

  /** Copy any URI (file:// or content://) to the persistent document directory. */
  const copyToPersistent = async (srcUri: string): Promise<string> => {
    // Compute dir at call time — never stale even after multiple renders
    const dir = `${FileSystem.documentDirectory ?? ''}closetmate_images/`;
    await FileSystem.makeDirectoryAsync(dir, { intermediates: true });
    const dest = `${dir}item_${Date.now()}.jpg`;
    try {
      // Fast path: direct copy (works for file:// camera URIs)
      await FileSystem.copyAsync({ from: srcUri, to: dest });
      console.log('[add-item] copyAsync OK ->', dest);
    } catch {
      // Fallback: read-as-base64 then write (works for Android gallery content:// URIs)
      console.warn('[add-item] copyAsync failed, trying base64 fallback');
      const b64 = await FileSystem.readAsStringAsync(srcUri, { encoding: FileSystem.EncodingType.Base64 });
      await FileSystem.writeAsStringAsync(dest, b64, { encoding: FileSystem.EncodingType.Base64 });
      console.log('[add-item] base64 fallback OK ->', dest);
    }
    return dest;
  };

  /** Decode a base64 data URI from /remove-bg and write to document directory. */
  const saveBase64ToPersistent = async (dataUri: string): Promise<string> => {
    const dir = `${FileSystem.documentDirectory ?? ''}closetmate_images/`;
    await FileSystem.makeDirectoryAsync(dir, { intermediates: true });
    const dest = `${dir}item_bg_${Date.now()}.jpg`;
    // Handle both image/jpeg and image/png MIME types
    const base64 = dataUri.replace(/^data:image\/[\w+]+;base64,/, '');
    await FileSystem.writeAsStringAsync(dest, base64, { encoding: FileSystem.EncodingType.Base64 });
    return dest;
  };

  // Plain async function — no useCallback — so it always closes over fresh
  // helper references and never has stale-closure bugs.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const processImage = async (uri: string) => {
    setRemovingBg(true);
    setAnalyzing(true);
    // Show original photo immediately so the screen isn't blank while we work
    setPreviewUri(uri);
    setPersistentImagePath('');

    // ── STEP 1: Copy original photo to document directory (instant, offline) ─
    // Gives us a persistent file:// path we can store in DB right away.
    // React Native renders file:// URIs efficiently at any size.
    let persistentFallback = uri; // raw camera URI as last resort
    try {
      persistentFallback = await copyToPersistent(uri);
      console.log('[add-item] copied to persistent storage:', persistentFallback);
      setPreviewUri(persistentFallback);        // upgrade preview to doc-dir copy
      setPersistentImagePath(persistentFallback); // can save now
    } catch (e) {
      console.warn('[add-item] copyToPersistent failed, using raw URI:', e);
      setPreviewUri(uri);
      setPersistentImagePath(uri); // still saveable, just not ideal
    }

    // ── STEP 2: Remove background + analyze metadata in parallel ──────────
    // Give removeBackground a 30-second timeout — Cloud Run cold starts
    // can take 15–20 s. After timeout we keep the original photo.
    const bgTimeout = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error('remove-bg timeout')), 30_000)
    );
    const [bgResult, analyzeResult] = await Promise.allSettled([
      Promise.race([removeBackground(uri), bgTimeout]),
      analyzeClothing(uri),
    ]);

    // ── Background removal ────────────────────────────────────────────────
    setRemovingBg(false);
    if (bgResult.status === 'fulfilled') {
      try {
        // Save the processed PNG to a persistent file (NOT a data URI)
        const processedPath = await saveBase64ToPersistent(bgResult.value);
        setPreviewUri(processedPath);
        setPersistentImagePath(processedPath); // upgrade to clean bg-removed image
        console.log('[add-item] bg removal saved to:', processedPath);
      } catch (e) {
        console.warn('[add-item] could not save bg result, keeping original:', e);
      }
    } else {
      console.warn('[add-item] removeBackground failed (using original):', bgResult.reason);
    }

    // ── Analyze autofill ──────────────────────────────────────────────────
    setAnalyzing(false);
    if (analyzeResult.status === 'fulfilled') {
      const { suggested, image_path } = analyzeResult.value;
      setImagePath(image_path ?? '');
      if (suggested.category)      setCategory(suggested.category);
      if (suggested.subcategory)   setSubcategory(suggested.subcategory);
      if (suggested.primary_color) setColor(suggested.primary_color);
      if (suggested.material)      setMaterial(suggested.material);
      if (suggested.pattern)       setPattern(suggested.pattern);
      if (suggested.formality)     setStyle(suggested.formality);
    } else {
      console.warn('[add-item] Analyze failed, manual input allowed:', analyzeResult.reason);
    }
  };  // end processImage


  // ── On param change (from FloatingCameraButton) ───────────────────────────
  useEffect(() => {
    if (params.imageUri) {
      setOriginalUri(params.imageUri);
      // processImage sets previewUri immediately, no need to clear it here
      processImage(params.imageUri);
    }
  }, [params.imageUri]);  // processImage is stable (plain function, no deps)

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
      quality: 0.9,
      allowsEditing: false,
    });

    if (!result.canceled) {
      const uri = result.assets[0].uri;
      setOriginalUri(uri);
      setPreviewUri(null);
      setPersistentImagePath("");
      processImage(uri);
    }
  };

  const clearPreview = () => {
    setOriginalUri(null);
    setPreviewUri(null);
    setPersistentImagePath("");
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
        user_id: activeUserId,
        // persistentImagePath is a file:// path in the app's document directory —
        // permanent storage that React Native renders efficiently at any image size.
        image_path: persistentImagePath,
        category:      category.trim()     || "unknown",
        subcategory:   subcategory.trim()  || "unknown",
        primary_color: color.trim()        || "unknown",
        material:      material.trim()     || "unknown",
        pattern:       pattern.trim()      || "solid",
        formality:     style.trim()        || "casual",
        culture:       "global",
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
