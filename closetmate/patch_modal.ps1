
$file = "f:\Projects\Closetmate\closetmate\app\(tabs)\stylist.tsx"
$content = [System.IO.File]::ReadAllText($file, [System.Text.Encoding]::UTF8)
$nl = [char]10

# Find the modal start (just after </KeyboardAvoidingView>)
$modalStart = $content.IndexOf("<Modal" + $nl + "        visible={showEnvModal}")
Write-Host "Modal start: $modalStart"

# Find </Modal>
$modalEnd = $content.IndexOf("</Modal>", $modalStart) + "</Modal>".Length
Write-Host "Modal end: $modalEnd"

$newModal = "<Modal" + $nl
$newModal += "        visible={showEnvModal}" + $nl
$newModal += "        transparent" + $nl
$newModal += '        animationType="slide"' + $nl
$newModal += "        onRequestClose={() => setShowEnvModal(false)}" + $nl
$newModal += "      >" + $nl
$newModal += "        <View style={styles.envModalOverlay}>" + $nl
$newModal += "          <View style={[styles.envModalCard, { backgroundColor: isDark ? '#1C1C1E' : '#FFFFFF' }]}>" + $nl

# Title row
$newModal += "            <View style={styles.envModalHeader}>" + $nl
$newModal += "              <Text style={styles.envModalIcon}>" + [char]0xD83C + [char]0xDF24 + "</Text>" + $nl
$newModal += "              <View style={{ flex: 1 }}>" + $nl
$newModal += "                <Text style={[styles.envModalTitle, { color: isDark ? '#FFF' : '#1A1A1A' }]}>" + $nl
$newModal += "                  Venue Type" + $nl
$newModal += "                </Text>" + $nl
$newModal += "                <Text style={[styles.envModalSub, { color: isDark ? '#AEAEB2' : '#6C6C70' }]}>" + $nl
$newModal += "                  Your AI stylist uses weather + skin tone + body shape for perfect outfit picks." + $nl
$newModal += "                </Text>" + $nl
$newModal += "              </View>" + $nl
$newModal += "            </View>" + $nl

# GPS status / city input
$newModal += "            {/* City override input */}" + $nl
$newModal += "            <View style={[styles.cityInputRow, { borderColor: isDark ? '#3A3A3C' : '#E5E5EA' }]}>" + $nl
$newModal += "              <Ionicons name=" + '"location-outline"' + " size={16} color={isDark ? '#636366' : '#AEAEB2'} />" + $nl
$newModal += "              <TextInput" + $nl
$newModal += "                style={[styles.cityTextInput, { color: isDark ? '#FFF' : '#1A1A1A' }]}" + $nl
$newModal += '                placeholder="Or type a city (e.g. London, Tokyo)"' + $nl
$newModal += "                placeholderTextColor={isDark ? '#636366' : '#AEAEB2'}" + $nl
$newModal += "                value={cityInput}" + $nl
$newModal += "                onChangeText={setCityInput}" + $nl
$newModal += '                returnKeyType="done"' + $nl
$newModal += '                autoCapitalize="words"' + $nl
$newModal += "              />" + $nl
$newModal += "              {pendingCoords && !cityInput && (" + $nl
$newModal += "                <View style={styles.gpsTag}>" + $nl
$newModal += "                  <Text style={styles.gpsTagText}>" + [char]0xD83D + [char]0xDCCD + " GPS</Text>" + $nl
$newModal += "                </View>" + $nl
$newModal += "              )}" + $nl
$newModal += "            </View>" + $nl

# Loading / error
$newModal += "            {locationLoading && (" + $nl
$newModal += "              <View style={styles.envLoadingRow}>" + $nl
$newModal += "                <ActivityIndicator size=" + '"small"' + " color=" + '"#0A84FF"' + " />" + $nl
$newModal += "                <Text style={[styles.envLoadingText, { color: isDark ? '#AEAEB2' : '#6C6C70' }]}>Fetching weather...</Text>" + $nl
$newModal += "              </View>" + $nl
$newModal += "            )}" + $nl
$newModal += "            {locationError && <Text style={styles.weatherErrorText}>{locationError}</Text>}" + $nl

# Venue buttons
$newModal += "            <Text style={[styles.envSectionLabel, { color: isDark ? '#AEAEB2' : '#6C6C70' }]}>Select venue</Text>" + $nl
$newModal += "            <TouchableOpacity style={[styles.envBigBtn, { backgroundColor: '#007AFF' }]} onPress={() => handleConfirmEnvironment('indoor')} activeOpacity={0.85}>" + $nl
$newModal += "              <Text style={styles.envBigIcon}>" + [char]0xD83C + [char]0xDFE0 + "</Text>" + $nl
$newModal += "              <View style={{ flex: 1 }}>" + $nl
$newModal += "                <Text style={styles.envBigLabel}>Indoor</Text>" + $nl
$newModal += "                <Text style={styles.envBigSub}>Office, mall, restaurant, home</Text>" + $nl
$newModal += "              </View>" + $nl
$newModal += "            </TouchableOpacity>" + $nl
$newModal += "            <TouchableOpacity style={[styles.envBigBtn, { backgroundColor: '#34C759' }]} onPress={() => handleConfirmEnvironment('outdoor')} activeOpacity={0.85}>" + $nl
$newModal += "              <Text style={styles.envBigIcon}>" + [char]0xD83C + [char]0xDF3F + "</Text>" + $nl
$newModal += "              <View style={{ flex: 1 }}>" + $nl
$newModal += "                <Text style={styles.envBigLabel}>Outdoor</Text>" + $nl
$newModal += "                <Text style={styles.envBigSub}>Park, street, events, travel</Text>" + $nl
$newModal += "              </View>" + $nl
$newModal += "            </TouchableOpacity>" + $nl
$newModal += "            <TouchableOpacity style={[styles.envBigBtn, { backgroundColor: '#FF9500' }]} onPress={() => handleConfirmEnvironment('both')} activeOpacity={0.85}>" + $nl
$newModal += "              <Text style={styles.envBigIcon}>" + [char]0xD83D + [char]0xDD04 + "</Text>" + $nl
$newModal += "              <View style={{ flex: 1 }}>" + $nl
$newModal += "                <Text style={styles.envBigLabel}>Both</Text>" + $nl
$newModal += "                <Text style={styles.envBigSub}>Moving between indoor and outdoor</Text>" + $nl
$newModal += "              </View>" + $nl
$newModal += "            </TouchableOpacity>" + $nl
$newModal += "            <TouchableOpacity style={styles.envSkipBtn} onPress={() => setShowEnvModal(false)}>" + $nl
$newModal += "              <Text style={[styles.envSkipText, { color: isDark ? '#636366' : '#AEAEB2' }]}>Skip for now</Text>" + $nl
$newModal += "            </TouchableOpacity>" + $nl
$newModal += "          </View>" + $nl
$newModal += "        </View>" + $nl
$newModal += "      </Modal>"

$newContent = $content.Substring(0, $modalStart) + $newModal + $content.Substring($modalEnd)
[System.IO.File]::WriteAllText($file, $newContent, [System.Text.Encoding]::UTF8)
Write-Host "SUCCESS: modal updated with city input + venue type label"
