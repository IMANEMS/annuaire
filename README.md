# annuaire

Récupère 3 000 établissements scolaires depuis l'API de l'annuaire de l'Éducation
nationale, garde ceux qui sont ouverts et ont un département, puis calcule le nombre
d'établissements par département, la part public/privé et les ouvertures par année.

## Installation

Prérequis : Python 3.12+ et [uv](https://docs.astral.sh/uv/).

```bash
   git clone https://github.com/IMANEMS/annuaire.git
   cd annuaire
uv sync
```

## Lancement

```bash
uv run annuaire-ingest --source api
```

Options :

```bash
uv run annuaire-ingest --source csv
uv run annuaire-ingest --source parquet
uv run annuaire-ingest --source api --nombre 500
```

Les sources CSV et Parquet lisent respectivement `donnees/etablissements.csv` et
`donnees/etablissements.parquet`. Les données de test se préparent avec
`python3 preparer_donnees.py` depuis le dossier parent du projet.

Le programme valide les enregistrements, compte les rejets par motif et exporte les
établissements ouverts dans `export_annuaire.csv`.

## TP4 — Mesures de performance

Jeu complet : **2 000 000 de lignes** (212 Mo) générées avec
`python3 ../generer_donnees.py --dossier donnees_tp4`, puis converties avec
`python convertir.py` et mesurées avec `python mesurer.py`. Les fichiers du TP4 sont
isolés dans `donnees_tp4/` pour préserver les données de la séance 3.

> Machine de mesure : Linux x86-64, 2 cœurs, Python 3.13, pandas 3.0, Polars 2.0.
> Lors d'une première tentative sur le Mac, la génération s'était arrêtée à 1 434 223
> lignes faute d'espace disque, et le Parquet datait encore du jeu de 200 000 lignes.
> Le script `mesurer.py` refuse maintenant ce cas. Depuis, le jeu complet a été régénéré
> et les quatre mesures ont été relancées sur le Mac; les résultats sont rapportés plus
> bas séparément.

### Étape 1 — Le poids des formats

| Format | Taille | Gain vs CSV |
|---|---:|---:|
| CSV | 212 Mo | 1,0× |
| Parquet sans compression | 40 Mo | 5,3× |
| Parquet snappy | 24 Mo | 9,0× |
| Parquet zstd | 14 Mo | 14,7× |
| Parquet zstd + catégories | 14 Mo | 14,7× |
| Parquet zstd partitionné (16 fichiers additionnés) | 29 Mo | 7,2× |

**Pourquoi un format colonne compresse-t-il mieux qu'un CSV, à données égales ?**
Le CSV range les valeurs ligne par ligne : un identifiant, un nom, une date, un
département… des valeurs de nature différente qui se suivent, donc peu de répétitions
exploitables. Parquet range toutes les valeurs d'une même colonne ensemble : elles
ont le même type et se répètent énormément (16 départements, 2 états, 2 statuts). Parquet
les encode d'abord par dictionnaire (chaque valeur distincte stockée une fois, puis des
petits entiers codés en RLE / bit-packing), et le compresseur (snappy, zstd) travaille
ensuite sur des données très homogènes. Résultat : 40 Mo avant même toute compression,
14 Mo avec zstd.

**Le partitionnement donne-t-il un fichier plus petit ? Sinon, à quoi sert-il ?**
Non : 29 Mo contre 14 Mo. Chacun des 16 fichiers repart avec son propre dictionnaire,
ses métadonnées et des blocs compressés plus petits, donc moins efficaces. Le
partitionnement sert à **lire moins** : une requête sur un département n'ouvre que son
dossier. Lire Paris seul prend 0,02 s, contre 0,14 s pour lire le fichier entier puis
filtrer.

**Pourquoi `category` ne change presque rien à la taille du Parquet ?** Parquet applique
déjà l'encodage par dictionnaire aux colonnes à faible cardinalité
(`RLE_DICTIONARY` dans les métadonnées). Le type `category` de pandas fait la même chose
en mémoire, donc il n'apporte rien de plus sur disque.

### Étape 2 et 3 — Quatre façons de compter

Chaque approche est lancée dans son propre processus (`mesurer.py`).

| Approche | Durée | Pic mémoire | × plus lent |
|---|---:|---:|---:|
| pandas naïf (boucle `iloc`) | 188,9 s | 884 Mo | 921× |
| pandas `apply` | 15,0 s | 2 037 Mo | 73× |
| pandas optimisé (`usecols` + `category` + vectorisé) | 2,3 s | 150 Mo | 11× |
| Polars différé sur Parquet | 0,2 s | 103 Mo | 1× |

Les quatre approches donnent exactement le même résultat :
**1 940 295 établissements ouverts**, avec le même détail par département.

**`apply` consomme-t-il plus ou moins de mémoire que la boucle `iloc` ? Pourquoi ?**
Plus, environ 2,3 fois plus (2 037 Mo contre 884 Mo). `apply(axis=1)` construit une
`Series` pour chacune des 2 millions de lignes et accumule les 2 millions de résultats
dans une nouvelle `Series` avant de créer le masque, puis la copie filtrée du DataFrame.
Tout cela s'ajoute au DataFrame complet déjà chargé. La boucle `iloc` crée aussi une
`Series` par ligne, mais la jette aussitôt et ne garde qu'un petit dictionnaire. Elle
est plus lente, mais elle a moins d'objets vivants en même temps.

**Les trois leviers qui séparent la plus lente de la plus rapide :**

1. **Lire moins** : seulement les 2 colonnes utiles sur 11 (`usecols`, ou la
   projection automatique de Polars sur Parquet). Avec pandas, lire 2 colonnes du
   Parquet prend 0,07 s contre 0,43 s pour tout le fichier. Un CSV ne permet pas ce
   gain : il faut parcourir chaque ligne en entier pour trouver les séparateurs.
2. **Un format colonne et typé** : Parquet évite d'analyser le texte du CSV et stocke
   déjà les valeurs encodées par dictionnaire, et `category` fait de même en mémoire.
3. **Vectoriser au lieu de boucler en Python** : une comparaison sur toute la colonne
   exécutée en C/Rust, au lieu de 2 millions d'itérations de l'interpréteur. Polars
   ajoute l'exécution différée : il optimise le plan (filtre et projection poussés
   jusqu'à la lecture) et parallélise sur les cœurs.

### Vérification complète sur le Mac

Après régénération du CSV complet, les quatre méthodes ont été relancées dans des
processus isolés sur macOS 26.6.2 arm64, Python 3.12.14. Les fichiers Parquet ont été
recréés depuis ce CSV.

| Approche | Durée | Pic mémoire | × plus lent |
|---|---:|---:|---:|
| pandas naïf (boucle `iloc`) | 50,7 s | 1 032 MiB | 185,1× |
| pandas `apply` | 5,4 s | 2 205 MiB | 19,7× |
| pandas optimisé | 0,9 s | 166 MiB | 3,2× |
| Polars différé sur Parquet | 0,3 s | 102 MiB | 1× |

Les quatre résultats concordent : **1 940 295 établissements ouverts**. Les tailles
mesurées sur le même Mac étaient de 212,00 MiB pour le CSV, 40,19 MiB pour Parquet sans
compression, 23,55 MiB avec Snappy, 14,45 MiB avec Zstd, 14,47 MiB avec Zstd et
catégories, et 29,26 MiB pour le dossier partitionné.

## Source des données

Jeu *Annuaire de l'éducation* (`fr-en-annuaire-education`), ministère de l'Éducation
nationale, https://data.education.gouv.fr — 3 000 enregistrements par défaut,
récupérés par pages de 100.

## TP5 — Tout ingérer, malgré l'API

```bash
uv run python -m annuaire --mur             # étape 1 : mesurer le plafond
uv run python -m annuaire --sauvegarder     # étapes 2 à 4 : tout sauvegarder
uv run python -m annuaire --cle             # étape 5 : la question de la clé
uv run python -m annuaire --source partitions   # analyser les 68 563
```

### Étape 1 — Le mur

L'API refuse dès que **`offset + limit > 10 000`**. La contrainte porte sur la somme,
pas sur l'offset seul :

| limit | plus grand offset accepté | offset + limit |
|---:|---:|---:|
| 1 | 9 999 | 10 000 |
| 100 | 9 900 | 10 000 |

`offset=9950&limit=100` échoue déjà. Une pagination à plat ne lit donc que les 10 000
premiers enregistrements.

### Étapes 2 à 4 — Partitionner, réessayer, reprendre

- **Partitions** : une par `code_departement` (aucune ne dépasse 10 000). La liste des
  partitions est elle-même paginée et lue jusqu'au bout.
- **Garde-fou** : la somme des effectifs des partitions est comparée au `total_count`
  de l'API ; si elle diffère, l'ingestion s'arrête (`IngestionIncomplete`). Même
  contrôle à la fin sur les lignes écrites.
- **Réessai** : `@reessayer()` (`src/annuaire/ingestion.py`, réglages dans `config.py`) — attente qui double
  (0,5 · 1 · 2 · 4 s), multipliée par un tirage dans [0,5 ; 1,5], `Retry-After` écouté,
  seuls 408/425/429/500/502/503/504 sont réessayés ; 400 et 404 remontent aussitôt.
- **Débit** : `Debit(5)` impose 0,2 s minimum entre deux appels.
- **Reprise** : un fichier `donnees/brut/dep=XXX.parquet` par partition, écrit dans
  `.partiel` puis renommé ; les partitions déjà présentes sont sautées.

### Résultat de l'ingestion

107 partitions (départements) sauvegardées dans `donnees/brut/`, **68 558 lignes = le
`total_count` de l'API** le 10 novembre 2026 (l'énoncé annonçait 68 563 : la source
bouge, c'est pourquoi on compare au total *du jour*).

### Étape 5 — La clé

```
lignes                  : 68558
identifiants distincts  : 68473
identifiants en double  : 78 (163 lignes)
```

**1. C'est la source qui duplique, pas notre partitionnement.** Preuves :

- Les partitions sont **disjointes** par construction : chaque fichier vient d'un
  `where code_departement="XXX"` différent. Or les **78 identifiants en double ont
  leurs copies dans le même fichier** (78 / 78). Notre découpage n'a donc rien recopié :
  l'API renvoie elle-même plusieurs lignes pour un seul filtre.
- Les copies **ne sont pas identiques** (0 / 78) : ce ne sont pas des pages relues deux
  fois, mais des fiches différentes. Exemple `0010053C` : le CIO d'Ambérieu-en-Bugey et
  son antenne de Belley, deux adresses et deux téléphones sous le même UAI.
- Les **163 lignes en double ont toutes `multi_uai = 1`**, et ce sont les seules
  (68 395 lignes à 0). La source signale elle-même ces établissements : plusieurs
  fiches (sites, antennes, fiches ONISEP) partagent un même UAI.

C'est donc un **défaut de donnée**, pas un défaut de code : la somme de nos partitions
égale le `total_count` de l'API, et aucun doublon ne traverse deux partitions.

**2. La clé pour dédupliquer.** `identifiant_de_l_etablissement` seul n'est pas une clé
pour ce jeu. La colonne qui diffère dans **toutes** les copies est `fiche_onisep` (78 / 78),
et le couple **(`identifiant_de_l_etablissement`, `fiche_onisep`)** est unique sur les
68 558 lignes (vérifié). C'est la clé d'une *ligne*. Si l'on veut une ligne par
*établissement* (UAI), il ne faut pas supprimer au hasard : il faut choisir une règle
(par exemple garder la fiche principale) ou agréger les sites — c'est une décision
métier, à documenter, pas un nettoyage technique.
