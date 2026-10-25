"""Real Open Food Facts discovery targets, not a product seed list."""

BRAND_GROUPS = [
    {"key": "dairy", "category": "Dairy", "brands": ["Amul", "Mother Dairy", "Nandini", "Milky Mist", "Aavin", "Hatsun", "Nestlé", "Epigamia"]},
    {"key": "biscuits-bakery", "category": "Biscuits and bakery", "brands": ["Britannia", "Parle", "Sunfeast", "Oreo", "McVitie's", "Unibic", "Harvest Gold"]},
    {"key": "cereals-breakfast", "category": "Cereals and breakfast", "brands": ["Kellogg's", "Quaker", "Bagrry's", "Saffola", "Tata Soulfull", "Yoga Bar", "True Elements"]},
    {"key": "chips-snacks", "category": "Chips and snacks", "brands": ["Lay's", "Kurkure", "Bingo!", "Haldiram's", "Bikaji", "Balaji Wafers", "Too Yumm!", "Cornitos"]},
    {"key": "chocolates", "category": "Chocolates", "brands": ["Cadbury", "Amul", "Nestlé", "Ferrero", "Mars", "Hershey's", "Lindt"]},
    {"key": "drinks", "category": "Drinks", "brands": ["Coca-Cola", "Pepsi", "Thums Up", "Sprite", "Fanta", "Paper Boat", "Real", "Tropicana", "Frooti", "Appy", "Red Bull"]},
    {"key": "packaged-water", "category": "Packaged water", "brands": ["Bisleri", "Kinley", "Aquafina", "Bailley"]},
    {"key": "grains", "category": "Rice, flour and grains", "brands": ["Aashirvaad", "Fortune", "India Gate", "Daawat", "Kohinoor", "Tata Sampann", "Pillsbury"]},
    {"key": "noodles-pasta", "category": "Noodles and pasta", "brands": ["Maggi", "Sunfeast YiPPee!", "Top Ramen", "Ching's Secret", "Knorr", "Wai Wai", "Bambino", "Del Monte"]},
    {"key": "oils-ghee", "category": "Oils and ghee", "brands": ["Fortune", "Saffola", "Dhara", "Sundrop", "Gold Winner", "Amul", "Gowardhan"]},
    {"key": "spices", "category": "Spices", "brands": ["MDH", "Everest", "Catch", "Tata Sampann", "Badshah", "Eastern", "Aachi", "Sakthi"]},
    {"key": "sauces-condiments", "category": "Sauces and condiments", "brands": ["Kissan", "Maggi", "Heinz", "Veeba", "FunFoods", "Del Monte", "Wingreens Farms"]},
    {"key": "ready-to-eat", "category": "Ready-to-eat foods", "brands": ["MTR", "Haldiram's", "Gits", "ITC Kitchens of India", "Tata Sampann"]},
    {"key": "yogurt", "category": "Yogurt", "brands": ["Amul", "Mother Dairy", "Milky Mist", "Epigamia", "Nestlé", "Nandini"]},
    {"key": "ice-cream", "category": "Ice cream", "brands": ["Amul", "Mother Dairy", "Vadilal", "Havmor", "Kwality Wall's", "Naturals", "Arun Icecreams"]},
    {"key": "frozen", "category": "Frozen foods", "brands": ["McCain", "Godrej Yummiez", "Venky's", "Sumeru", "Safal"]},
    {"key": "nuts-protein", "category": "Nuts, spreads and protein foods", "brands": ["Pintola", "Alpino", "Happilo", "Farmley", "RiteBite Max Protein", "The Whole Truth Foods"]},
    {"key": "tea-coffee", "category": "Tea and coffee", "brands": ["Tata Tea", "Brooke Bond", "Wagh Bakri", "Society Tea", "Nescafé", "Bru", "Continental Coffee", "Rage Coffee"]},
    {"key": "pickles-regional", "category": "Pickles and regional foods", "brands": ["Mother's Recipe", "Priya", "Nilon's", "Pachranga", "Aachi", "Sakthi"]},
    {"key": "baby-specialized", "category": "Baby food and specialized nutrition", "brands": ["Nestlé Cerelac", "Lactogen", "Aptamil", "Similac"]},
]

def all_brand_names():
    return sorted({brand for group in BRAND_GROUPS for brand in group["brands"]}, key=str.casefold)
