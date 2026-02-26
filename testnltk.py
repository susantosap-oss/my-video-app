import nltk
import re

# Simulasi teks deskripsi mansion
deskripsi = "Mansion mewah di Citraland. Memiliki 5 kamar tidur dan kolam renang. Lokasi sangat strategis dekat mall. Harga nego sampai jadi!"

print("--- Mengetes Pemecah Kalimat ---")

try:
    # Cara NLTK
    nltk.download('punkt', quiet=True)
    sentences = nltk.sent_tokenize(deskripsi)
    print(f"Hasil NLTK ({len(sentences)} kalimat):")
    for i, s in enumerate(sentences):
        print(f"{i+1}. {s.upper()}")
except Exception as e:
    # Cara Manual (Fallback)
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', deskripsi) if s.strip()]
    print(f"Hasil Manual ({len(sentences)} kalimat):")
    for i, s in enumerate(sentences):
        print(f"{i+1}. {s.upper()}")