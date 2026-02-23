import {
  View,
  Text,
  Image,
  Pressable,
  ActivityIndicator,
  StyleSheet,
  SafeAreaView,
  TouchableOpacity,
  useColorScheme,
  Dimensions,
  TextInput,
  Alert,
} from "react-native";
import * as ImagePicker from "expo-image-picker";
import { useState, useEffect, useCallback } from "react";
import { useLocalSearchParams, useRouter } from "expo-router";
import { styleImage } from "@/src/api/ai";
import { Ionicons } from "@expo/vector-icons";

const { width } = Dimensions.get("window");
const CAPTURE_SIZE = width - 48;
const PREVIEW_SIZE = 80;

export default function AddItemScreen() {
  const params = useLocalSearchParams<{ imageUri?: string }>();
  const router = useRouter();
  const colorScheme = useColorScheme();
  const isDark = colorScheme === "dark";

  const [originalUri, setOriginalUri] = useState<string | null>(null);
  const [styledUri, setStyledUri] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [category, setCategory] = useState("Top");
  const [color, setColor] = useState("Green");
  const [material, setMaterial] = useState("Silk");
  const [style, setStyle] = useState("Traditional");

  const upload = useCallback(async (uri: string) => {
    setLoading(true);
    try {
      const styled = await styleImage(uri);
      setStyledUri(styled);
    } catch (e) {
      setStyledUri(null);
      const message = e instanceof Error ? e.message : "Unknown error";
      Alert.alert(
        "Processing failed",
        message,
        [{ text: "OK" }]
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (params.imageUri) {
      setOriginalUri(params.imageUri);
      setStyledUri(null);
      upload(params.imageUri);
    }
  }, [params.imageUri, upload]);

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
      setOriginalUri(result.assets[0].uri);
      setStyledUri(null);
      upload(result.assets[0].uri);
    }
  };

  const clearPreview = () => {
    setOriginalUri(null);
    setStyledUri(null);
  };

  const displayUri = styledUri ?? originalUri;
  const hasImage = !!originalUri;

  const styles = createStyles(isDark);

  return (
    <SafeAreaView style={styles.safeArea}>
      {/* Top bar: flash (left), flip (right) */}
      <View style={styles.topBar}>
        <TouchableOpacity style={styles.topIcon} hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}>
          <Ionicons name="flash-outline" size={26} color={isDark ? "#FFF" : "#000"} />
        </TouchableOpacity>
        <TouchableOpacity style={styles.topIcon} hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}>
          <Ionicons name="camera-reverse-outline" size={26} color={isDark ? "#FFF" : "#000"} />
        </TouchableOpacity>
      </View>

      {/* Capture area: dashed frame with image or tap to capture */}
      <View style={styles.captureWrapper}>
        <Pressable style={styles.captureArea} onPress={!hasImage ? pickImage : undefined}>
          {hasImage ? (
            <Image
              source={{ uri: displayUri }}
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
            </View>
          )}
        </Pressable>
      </View>

      {/* Preview thumbnail + X */}
      {hasImage && (
        <View style={styles.previewRow}>
          <View style={styles.previewThumbWrapper}>
            <Image
              source={{ uri: displayUri }}
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

      {/* Form card: Category, Color, Material, Style */}
      <View style={styles.formCard}>
        <View style={styles.formRow}>
          <Text style={styles.formLabel}>Category:</Text>
          <TextInput
            style={styles.formInput}
            value={category}
            onChangeText={setCategory}
            placeholder="e.g. Top"
            placeholderTextColor={isDark ? "#636366" : "#8E8E93"}
          />
        </View>
        <View style={styles.formRow}>
          <Text style={styles.formLabel}>Color:</Text>
          <TextInput
            style={styles.formInput}
            value={color}
            onChangeText={setColor}
            placeholder="e.g. Green"
            placeholderTextColor={isDark ? "#636366" : "#8E8E93"}
          />
        </View>
        <View style={styles.formRow}>
          <Text style={styles.formLabel}>Material:</Text>
          <TextInput
            style={styles.formInput}
            value={material}
            onChangeText={setMaterial}
            placeholder="e.g. Silk"
            placeholderTextColor={isDark ? "#636366" : "#8E8E93"}
          />
        </View>
        <View style={styles.formRow}>
          <Text style={styles.formLabel}>Style:</Text>
          <TextInput
            style={styles.formInput}
            value={style}
            onChangeText={setStyle}
            placeholder="e.g. Traditional"
            placeholderTextColor={isDark ? "#636366" : "#8E8E93"}
          />
        </View>
      </View>

      {/* Confirm button */}
      <Pressable
        style={[styles.confirmButton, !styledUri && styles.confirmButtonDisabled]}
        onPress={styledUri ? () => router.back() : undefined}
        disabled={!styledUri}
      >
        <Text style={styles.confirmButtonText}>Confirm & Add to Closet</Text>
      </Pressable>
    </SafeAreaView>
  );
}

function createStyles(isDark: boolean) {
  return StyleSheet.create({
    safeArea: {
      flex: 1,
      backgroundColor: isDark ? "#000" : "#FFF",
      paddingHorizontal: 24,
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
      backgroundColor: "rgba(0,0,0,0.5)",
      justifyContent: "center",
      alignItems: "center",
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
      width: 90,
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
      opacity: 0.6,
    },
    confirmButtonText: {
      fontSize: 16,
      fontWeight: "600",
      color: "#FFFFFF",
    },
  });
}
