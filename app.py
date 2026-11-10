"""Annuaire des établissements scolaires : web app Streamlit.

Lancer depuis le dossier `annuaire` :

    uv run streamlit run app.py

Les données viennent de `donnees/etablissements_complet.csv`, produit par
l'ingestion du TP 5 (`uv run python -m annuaire --sauvegarder`).
"""

from pathlib import Path

import pandas as pd
import streamlit as st

FICHIER = Path(__file__).parent / "donnees" / "etablissements_complet.csv"
TOUS = "Tous"
COLONNES_AFFICHEES = {
    "identifiant_de_l_etablissement": "UAI",
    "nom_etablissement": "Nom",
    "type_etablissement": "Type",
    "statut_public_prive": "Statut",
    "etat": "État",
    "nom_commune": "Commune",
    "code_postal": "Code postal",
    "libelle_departement": "Département",
    "libelle_region": "Région",
    "adresse_1": "Adresse",
    "telephone": "Téléphone",
    "mail": "E-mail",
    "web": "Site web",
    "date_ouverture": "Ouverture",
}


@st.cache_data(show_spinner="Chargement des 68 000 établissements…")
def charger(chemin: Path) -> pd.DataFrame:
    """Lit le CSV une seule fois (mis en cache entre deux interactions)."""
    donnees = pd.read_csv(chemin, dtype=str)  # garde les zéros : 01505, 001
    for colonne in ("latitude", "longitude"):
        donnees[colonne] = pd.to_numeric(donnees[colonne], errors="coerce")
    for colonne in ("type_etablissement", "statut_public_prive", "libelle_region"):
        donnees[colonne] = donnees[colonne].fillna("Non renseigné")
    donnees["etat"] = donnees["etat"].fillna("NON RENSEIGNÉ").str.upper()
    return donnees


def options(serie: pd.Series) -> list[str]:
    return sorted(serie.dropna().unique())


st.set_page_config(page_title="Annuaire de l'éducation", page_icon="🏫", layout="wide")
st.title("🏫 Annuaire des établissements scolaires")

if not FICHIER.exists():
    st.error(
        f"Fichier introuvable : `{FICHIER}`. Lancez d'abord l'ingestion "
        "(`uv run python -m annuaire --sauvegarder`), qui écrit aussi le CSV."
    )
    st.stop()

df = charger(FICHIER)

# --- Filtres -------------------------------------------------------------------
with st.sidebar:
    st.header("Filtres")
    recherche = st.text_input(
        "🔎 Nom, commune ou UAI", placeholder="ex. Lycée Victor Hugo"
    )

    etats_presents = options(df["etat"])
    choix_etat = st.radio("État", [TOUS, "Ouvert", "Fermé"], horizontal=True, index=0)
    if etats_presents == ["OUVERT"]:
        st.caption("ℹ️ La source data.gouv ne publie que des établissements ouverts.")

    regions = st.multiselect("Région", options(df["libelle_region"]))
    base_dep = df[df["libelle_region"].isin(regions)] if regions else df
    departements = st.multiselect(
        "Département", options(base_dep["libelle_departement"])
    )
    types = st.multiselect("Type d'établissement", options(df["type_etablissement"]))
    statut = st.radio("Statut", [TOUS, "Public", "Privé"], horizontal=True)

    with st.expander("Plus de filtres"):
        restauration = st.checkbox("Avec restauration")
        hebergement = st.checkbox("Avec internat (hébergement)")
        post_bac = st.checkbox("Avec formations post-bac")

# --- Application des filtres ---------------------------------------------------
masque = pd.Series(True, index=df.index)
if recherche:
    texte = recherche.strip()
    masque &= (
        df["nom_etablissement"].str.contains(texte, case=False, na=False, regex=False)
        | df["nom_commune"].str.contains(texte, case=False, na=False, regex=False)
        | df["identifiant_de_l_etablissement"].str.contains(
            texte, case=False, na=False, regex=False
        )
    )
if choix_etat == "Ouvert":
    masque &= df["etat"] == "OUVERT"
elif choix_etat == "Fermé":
    masque &= df["etat"].str.startswith("FERM")
if regions:
    masque &= df["libelle_region"].isin(regions)
if departements:
    masque &= df["libelle_departement"].isin(departements)
if types:
    masque &= df["type_etablissement"].isin(types)
if statut != TOUS:
    masque &= df["statut_public_prive"] == statut
for coche, colonne in (
    (restauration, "restauration"),
    (hebergement, "hebergement"),
    (post_bac, "post_bac"),
):
    if coche:
        masque &= pd.to_numeric(df[colonne], errors="coerce") == 1  # "1" ou "1.0"

resultat = df[masque]  # le CSV est déjà dédoublonné : une ligne par UAI

# --- Indicateurs ---------------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Établissements", f"{len(resultat):,}".replace(",", " "))
c2.metric("Ouverts", f"{(resultat['etat'] == 'OUVERT').sum():,}".replace(",", " "))
c3.metric(
    "Fermés", f"{resultat['etat'].str.startswith('FERM').sum():,}".replace(",", " ")
)
part_public = (
    (resultat["statut_public_prive"] == "Public").mean() if len(resultat) else 0
)
c4.metric("Public", f"{part_public:.0%}")

if resultat.empty:
    st.warning("Aucun établissement ne correspond à ces filtres.")
    st.stop()

# --- Onglets -------------------------------------------------------------------
onglet_liste, onglet_carte, onglet_stats = st.tabs(
    ["📋 Annuaire", "🗺️ Carte", "📊 Répartition"]
)

with onglet_liste:
    tableau = resultat[list(COLONNES_AFFICHEES)].rename(columns=COLONNES_AFFICHEES)
    st.dataframe(
        tableau,
        hide_index=True,
        width="stretch",
        height=560,
        column_config={"Site web": st.column_config.LinkColumn("Site web")},
    )
    st.download_button(
        "⬇️ Télécharger la sélection (CSV)",
        resultat.to_csv(index=False).encode("utf-8"),
        file_name="etablissements_selection.csv",
        mime="text/csv",
    )

with onglet_carte:
    points = resultat.dropna(subset=["latitude", "longitude"])
    MAX_POINTS = 20_000
    if len(points) > MAX_POINTS:
        st.caption(
            f"{len(points):,} établissements : affichage d'un échantillon de "
            f"{MAX_POINTS:,}. Filtrez pour tout voir.".replace(",", " ")
        )
        points = points.sample(MAX_POINTS, random_state=0)
    st.map(points, latitude="latitude", longitude="longitude", size=20)

with onglet_stats:
    gauche, droite = st.columns(2)
    with gauche:
        st.subheader("Par type")
        st.bar_chart(resultat["type_etablissement"].value_counts(), horizontal=True)
    with droite:
        st.subheader("Top 15 des départements")
        st.bar_chart(
            resultat["libelle_departement"].value_counts().head(15), horizontal=True
        )
