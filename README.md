# Veille encheres materiel de laboratoire — flux RSS automatise

Ce depot genere et republie automatiquement un flux RSS (`feed.xml`) regroupant les
nouvelles annonces d'encheres de materiel de laboratoire, a partir des sites listes dans
`sites.yaml`.

Voir le protocole complet fourni a cote de ce depot pour la mise en place pas-a-pas
(creation du depot GitHub, activation de GitHub Pages, reperage des selecteurs CSS,
activation de la tache planifiee).

## Contenu

- `sites.yaml` — liste des sites a surveiller et selecteurs CSS pour chacun.
- `scraper.py` — lit `sites.yaml`, extrait les annonces, deduplique, regenere `feed.xml`.
- `requirements.txt` — dependances Python.
- `.github/workflows/update-feed.yml` — tache planifiee GitHub Actions (toutes les 6h),
  relance `scraper.py` et republie automatiquement les changements.
- `data/seen.json` — memoire des annonces deja vues (genere automatiquement, ne pas editer a la main).
- `feed.xml` — le flux RSS final, a donner a ton lecteur RSS une fois GitHub Pages active.

## Lancer manuellement (optionnel, pour tester en local)

```
pip install -r requirements.txt
playwright install --with-deps chromium   # uniquement si un site a js: true dans sites.yaml
python scraper.py
```

## Lancer sur GitHub sans rien installer

Une fois le depot pousse sur GitHub et GitHub Pages active, tout tourne automatiquement
via l'onglet **Actions** — voir le protocole pour les etapes.
