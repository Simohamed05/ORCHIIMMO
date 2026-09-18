# Orchiimmo — notes pour les prochaines sessions

## Fait
- Audit des 6 sources actives (Mubawab, Avito, Sarouty, Masaken, Bikhir,
  Yakeey) dans `properties/scraper.py` : deux trous trouvés et corrigés
  (Avito `_parse_soup_card` ne remplissait ni chambres ni SDB ; Masaken
  ne remplissait jamais les SDB). Les 4 autres extrayaient déjà tout
  correctement.
