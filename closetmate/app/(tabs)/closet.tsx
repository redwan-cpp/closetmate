import React, { useState } from 'react';
import { StyleSheet, FlatList, View, SafeAreaView, TouchableOpacity } from 'react-native';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { ClothingCard } from '@/components/ClothingCard';
import { FilterChip } from '@/components/filter-chip';
import { MOCK_CLOSET_ITEMS } from '@/constants/MockData';
import { Colors, Spacing } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { Ionicons } from '@expo/vector-icons';

const FILTERS = ['All', 'Tops', 'Bottoms', 'Dresses', 'Footwear'];

export default function ClosetScreen() {
  const colorScheme = useColorScheme();
  const theme = colorScheme ?? 'light';
  const [selectedFilter, setSelectedFilter] = useState('All');

  const filteredItems = selectedFilter === 'All'
    ? MOCK_CLOSET_ITEMS
    : MOCK_CLOSET_ITEMS.filter(item => item.category === selectedFilter);

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: Colors[theme].background }}>
      <ThemedView style={styles.container}>
        <View style={styles.header}>
          <ThemedText type="title">My Closet</ThemedText>
          <TouchableOpacity style={styles.searchButton} hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}>
            <Ionicons name="search" size={24} color={Colors[theme].icon} />
          </TouchableOpacity>
        </View>

        <View style={styles.filtersWrapper}>
          <FlatList
            horizontal
            data={FILTERS}
            keyExtractor={(item) => item}
            renderItem={({ item }) => (
              <FilterChip
                label={item}
                selected={selectedFilter === item}
                onPress={() => setSelectedFilter(item)}
              />
            )}
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.filtersContainer}
          />
        </View>

        <FlatList
          data={filteredItems}
          keyExtractor={(item) => item.id}
          renderItem={({ item }) => (
            <ClothingCard
              image={item.image}
              onPress={() => console.log('Item pressed', item.id)}
            />
          )}
          numColumns={2}
          columnWrapperStyle={styles.columnWrapper}
          contentContainerStyle={styles.gridContent}
          showsVerticalScrollIndicator={false}
          ListEmptyComponent={
            <View style={styles.emptyState}>
              <ThemedText>No items found.</ThemedText>
            </View>
          }
        />
      </ThemedView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    paddingHorizontal: Spacing.m,
    paddingTop: Spacing.l,
    paddingBottom: Spacing.s,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  searchButton: {
    padding: 4,
  },
  filtersWrapper: {
    marginBottom: Spacing.m,
  },
  filtersContainer: {
    paddingHorizontal: Spacing.m,
  },
  gridContent: {
    paddingHorizontal: Spacing.m,
    paddingBottom: 100, // Space for tab bar
  },
  columnWrapper: {
    justifyContent: 'space-between',
  },
  emptyState: {
    padding: Spacing.xl,
    alignItems: 'center',
  }
});
