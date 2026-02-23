import React from 'react';
import { StyleSheet, FlatList, View, SafeAreaView } from 'react-native';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { ExploreCard } from '@/components/explore-card';
import { AIInsightCard } from '@/components/AIInsightCard';
import { MOCK_EXPLORE_FEED } from '@/constants/MockData';
import { Colors, Spacing } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';

export default function ExploreScreen() {
  const colorScheme = useColorScheme();
  const theme = colorScheme ?? 'light';

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: Colors[theme].background }}>
      <ThemedView style={styles.container}>
        <View style={styles.header}>
          <ThemedText type="title">Explore</ThemedText>
        </View>

        <FlatList
          data={MOCK_EXPLORE_FEED}
          keyExtractor={(item) => item.id}
          renderItem={({ item, index }) => {
            // Insert AI Insight occasionally
            if (index === 1) {
              return (
                <View>
                  <AIInsightCard text="Based on your closet, adding a beige trench coat would unlock 15+ new outfit combinations." />
                  <ExploreCard
                    image={item.image}
                    title={item.title}
                    author={item.author}
                    likes={item.likes}
                  />
                </View>
              );
            }
            return (
              <ExploreCard
                image={item.image}
                title={item.title}
                author={item.author}
                likes={item.likes}
              />
            );
          }}
          numColumns={2}
          columnWrapperStyle={styles.columnWrapper}
          contentContainerStyle={styles.content}
          showsVerticalScrollIndicator={false}
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
    paddingBottom: Spacing.m,
  },
  content: {
    paddingHorizontal: Spacing.m,
    paddingBottom: 100,
  },
  columnWrapper: {
    justifyContent: 'space-between',
  },
});
