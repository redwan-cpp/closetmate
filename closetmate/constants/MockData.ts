
export const MOCK_MESSAGES = [
    {
        id: '1',
        text: "Hi there! I'm your digital stylist. Need help with an outfit today?",
        sender: 'system',
        timestamp: '9:00 AM',
    },
    {
        id: '2',
        text: "Yes, I have a dinner date tonight. Smart casual.",
        sender: 'user',
        timestamp: '9:05 AM',
    },
    {
        id: '3',
        text: "Got it! purely casual or a bit more dressed up?",
        sender: 'system',
        timestamp: '9:06 AM',
    },
    {
        id: '4',
        text: "Definitely dressed up. It's at a nice Italian place.",
        sender: 'user',
        timestamp: '9:07 AM',
    },
    {
        id: '5',
        text: "How about this combination?",
        sender: 'system',
        timestamp: '9:08 AM',
        imageUrl: 'https://images.unsplash.com/photo-1594938298603-c8148c47e356?w=600&auto=format&fit=crop&q=60&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxzZWFyY2h8MTl8fG1lbnMlMjBmYXNoaW9ufGVufDB8fDB8fHww', // Placeholder
    },
];

export const MOCK_CLOSET_ITEMS = [
    { id: '1', image: 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=600&auto=format&fit=crop&q=60&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxzZWFyY2h8Mnx8dCUyMHNoaXJ0fGVufDB8fDB8fHww', category: 'Tops' },
    { id: '2', image: 'https://images.unsplash.com/photo-1620799140408-ed5341cd2431?w=600&auto=format&fit=crop&q=60&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxzZWFyY2h8Nnx8dCUyMHNoaXJ0fGVufDB8fDB8fHww', category: 'Tops' },
    { id: '3', image: 'https://images.unsplash.com/photo-1591195853828-11db59a44c6b?w=600&auto=format&fit=crop&q=60&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxzZWFyY2h8Mnx8amVhbnN8ZW58MHx8MHx8fDA%3D', category: 'Bottoms' },
    { id: '4', image: 'https://images.unsplash.com/photo-1582552938357-32b906df40cb?w=600&auto=format&fit=crop&q=60&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxzZWFyY2h8NHx8amVhbnN8ZW58MHx8MHx8fDA%3D', category: 'Bottoms' },
    { id: '5', image: 'https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=600&auto=format&fit=crop&q=60&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxzZWFyY2h8Mnx8c2hvZXMlMjBuaWtlfGVufDB8fDB8fHww', category: 'Footwear' },
    { id: '6', image: 'https://images.unsplash.com/photo-1600269452121-4f2416e55c28?w=600&auto=format&fit=crop&q=60&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxzZWFyY2h8Mnx8c25lYWtlcnN8ZW58MHx8MHx8fDA%3D', category: 'Footwear' },
    { id: '7', image: 'https://images.unsplash.com/photo-1591047139829-d91aecb6caea?w=600&auto=format&fit=crop&q=60&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxzZWFyY2h8Mnx8amFja2V0fGVufDB8fDB8fHww', category: 'Tops' },
    { id: '8', image: 'https://images.unsplash.com/photo-1551028919-ac66c5f85955?w=600&auto=format&fit=crop&q=60&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxzZWFyY2h8NHx8amFja2V0fGVufDB8fDB8fHww', category: 'Tops' },
    { id: '9', image: 'https://images.unsplash.com/photo-1595777457583-95e059d581b8?w=600&auto=format&fit=crop&q=60', category: 'Dresses' },
    { id: '10', image: 'https://images.unsplash.com/photo-1572804013309-59a88b7e92f1?w=600&auto=format&fit=crop&q=60', category: 'Dresses' },
];

export const MOCK_OUTFITS = [
    {
        id: '1',
        image: 'https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?w=600&auto=format&fit=crop&q=60&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxzZWFyY2h8Mnx8b3V0Zml0fGVufDB8fDB8fHww',
        title: 'Fusion Friday Inspo',
        author: 'Elena Yu',
        likes: 245,
    },
    {
        id: '2',
        image: 'https://images.unsplash.com/photo-1550614000-4b9519e09d5f?w=600&auto=format&fit=crop&q=60&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxzZWFyY2h8Nnx8b3V0Zml0fGVufDB8fDB8fHww',
        title: 'Modern Linen Kurta',
        author: 'Marc Go',
        likes: 189,
    },
    {
        id: '3',
        image: 'https://images.unsplash.com/photo-1483985988355-763728e1935b?w=600&auto=format&fit=crop&q=60&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxzZWFyY2h8M3x8ZmFzaGlvbnxlbnwwfHwwfHx8MA%3D%3D',
        title: 'Evening Chic',
        author: 'StyleBot',
        likes: 542,
    },
    {
        id: '4',
        image: 'https://images.unsplash.com/photo-1485968579580-b6d095142e6e?w=600&auto=format&fit=crop&q=60&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxzZWFyY2h8MTZ8fGZhc2hpb258ZW58MHx8MHx8fDA%3D',
        title: 'Coffee Date',
        author: 'Sarah Jenkins',
        likes: 310,
    },
];

export const MOCK_PROFILE = {
    name: 'Alex Johnson',
    handle: '@alexjstyle',
    avatar: 'https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=600&auto=format&fit=crop&q=60&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxzZWFyY2h8Mnx8cHJvZmlsZSUyMHBob3RvfGVufDB8fDB8fHww',
    followers: '1.2k',
    following: '480',
    stats: {
        items: 48,
        outfits: 12,
    },
};

export const MOCK_EXPLORE_FEED = [
    ...MOCK_OUTFITS,
    {
        id: '5',
        image: 'https://images.unsplash.com/photo-1552374196-1ab2a1c593e8?w=600&auto=format&fit=crop&q=60&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxzZWFyY2h8MXx8bWVucyUyMGZhc2hpb258ZW58MHx8MHx8fDA%3D',
        title: 'Business Casual',
        author: 'MenStylePro',
        likes: 890,
    },
    {
        id: '6',
        image: 'https://images.unsplash.com/photo-1617137968427-85924c800a22?w=600&auto=format&fit=crop&q=60&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxzZWFyY2h8M3x8bWVucyUyMGZhc2hpb258ZW58MHx8MHx8fDA%3D',
        title: 'Weekend Vibes',
        author: 'Dave C.',
        likes: 120,
    },
];

export const MOCK_PROFILE_EXTENDED = {
    name: 'Anya Sharma',
    handle: '@anyastyle',
    avatar: 'https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=600&auto=format&fit=crop&q=60&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxzZWFyY2h8Mnx8cHJvZmlsZSUyMHBob3RvfGVufDB8fDB8fHww',
    bodyShape: 'Pear',
    skinToneIndex: 3,
    styleInsight: 'You wear your blue jeans frequently. Consider pairing them with your new white linen shirt for a fresh look.',
    wornHistory: [
        { day: 'M', date: 10, image: 'https://images.unsplash.com/photo-1595777457583-95e059d581b8?w=200&h=200&fit=crop' },
        { day: 'T', date: 11, image: null },
        { day: 'W', date: 12, image: 'https://images.unsplash.com/photo-1591195853828-11db59a44c6b?w=200&h=200&fit=crop' },
        { day: 'T', date: 13, image: 'https://images.unsplash.com/photo-1572804013309-59a88b7e92f1?w=200&h=200&fit=crop' },
        { day: 'F', date: 14, image: 'https://images.unsplash.com/photo-1610701596007-11502861dcfa?w=200&h=200&fit=crop' },
        { day: 'S', date: 15, image: 'https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=200&h=200&fit=crop' },
    ],
};

const SKIN_TONE_COLORS = ['#FFDBAC', '#F1C27D', '#E0AC69', '#C68642', '#8D5524', '#5C3317', '#3d2314', '#2d1b0e', '#1a0f0a'];
export { SKIN_TONE_COLORS };
