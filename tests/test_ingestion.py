"""Tests de l'ingestion du TP 5, sans réseau : API simulée par MockTransport."""

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import httpx
import pandas as pd

from annuaire import ingestion
from annuaire.ingestion import (
    Api,
    Debit,
    EchecDefinitif,
    IngestionIncomplete,
    reessayer,
    trouver_mur,
)
from annuaire.ingestion import sauvegarder_tout as ingerer


def fausse_base() -> list[dict[str, Any]]:
    """250 établissements répartis sur 3 départements, plus 2 sans département."""
    lignes = []
    for i in range(250):
        code = ("001", "059", "975")[i % 3]
        lignes.append(
            {"identifiant_de_l_etablissement": f"{i:07d}X", "code_departement": code}
        )
    lignes += [
        {"identifiant_de_l_etablissement": "SANSDEP1", "code_departement": None},
        {"identifiant_de_l_etablissement": "SANSDEP2", "code_departement": None},
    ]
    return lignes


class FausseApi:
    """Respecte le contrat de la vraie : plafond sur la somme, group_by, where."""

    def __init__(
        self,
        base: list[dict[str, Any]],
        pannes: list[int] | None = None,
        groupes_par_page_max: int | None = None,
    ) -> None:
        self.base = base
        self.pannes = list(pannes or [])
        self.groupes_par_page_max = groupes_par_page_max
        self.appels = 0

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        self.appels += 1
        if self.pannes:
            code = self.pannes.pop(0)
            entetes = {"Retry-After": "0"} if code == 429 else {}
            return httpx.Response(code, headers=entetes, json={"message": "panne"})
        p = requete.url.params
        limite, offset = int(p.get("limit", 10)), int(p.get("offset", 0))
        if offset + limite > ingestion.PLAFOND_API:
            return httpx.Response(400, json={"message": "sum of offset + limit"})
        lignes = self.base
        where = p.get("where")
        if where is not None:
            if where == "code_departement is null":
                lignes = [x for x in lignes if x["code_departement"] is None]
            elif where.startswith('code_departement="') and where.endswith('"'):
                code = where[len('code_departement="') : -1]
                lignes = [x for x in lignes if x["code_departement"] == code]
            else:
                return httpx.Response(400, json={"message": "where mal formé"})
        if p.get("group_by"):
            compte: dict[str | None, int] = {}
            for x in lignes:
                compte[x["code_departement"]] = compte.get(x["code_departement"], 0) + 1
            groupes = [
                {"code_departement": c, "n": n}
                for c, n in sorted(compte.items(), key=lambda kv: str(kv[0]))
            ]
            taille = min(limite, self.groupes_par_page_max or limite)
            return httpx.Response(
                200, json={"results": groupes[offset : offset + taille]}
            )
        tri = sorted(lignes, key=lambda x: x["identifiant_de_l_etablissement"])
        return httpx.Response(
            200,
            json={"total_count": len(lignes), "results": tri[offset : offset + limite]},
        )


def api_simulee(fausse: FausseApi) -> Api:
    client = httpx.Client(transport=httpx.MockTransport(fausse))
    return Api(client, Debit(par_seconde=10_000))


class SansDormir(unittest.TestCase):
    """Neutralise les pauses pour que les tests soient instantanés."""

    def setUp(self) -> None:
        self.pauses: list[float] = []
        patch = mock.patch("annuaire.ingestion.time.sleep", self.pauses.append)
        patch.start()
        self.addCleanup(patch.stop)


class ReessaiTests(SansDormir):
    def test_panne_passagere_rattrapee(self) -> None:
        fausse = FausseApi(fausse_base(), pannes=[503, 502])
        reponse = api_simulee(fausse).lire({"limit": 1})
        self.assertEqual(reponse["total_count"], 252)
        self.assertEqual(fausse.appels, 3)

    def test_400_et_404_remontent_immediatement(self) -> None:
        for code in (400, 404):
            fausse = FausseApi(fausse_base(), pannes=[code] * 5)
            with self.assertRaises(httpx.HTTPStatusError):
                api_simulee(fausse).lire({"limit": 1})
            self.assertEqual(fausse.appels, 1, code)
        self.assertEqual(self.pauses, [])

    def test_attente_double_et_bruitee(self) -> None:
        @reessayer(tentatives=5, attente_initiale=0.5)
        def toujours_503() -> None:
            raise httpx.HTTPStatusError(
                "panne",
                request=httpx.Request("GET", "https://x.test"),
                response=httpx.Response(503),
            )

        with self.assertRaises(EchecDefinitif):
            toujours_503()
        self.assertEqual(len(self.pauses), 4)  # 5 tentatives, 4 pauses
        for pause, base in zip(self.pauses, (0.5, 1.0, 2.0, 4.0), strict=True):
            self.assertTrue(base * 0.5 <= pause <= base * 1.5, (pause, base))
        with self.assertRaises(EchecDefinitif):
            toujours_503()
        self.assertNotEqual(self.pauses[:4], self.pauses[4:])  # pas déterministe

    def test_retry_after_ecoute(self) -> None:
        fausse = FausseApi(fausse_base(), pannes=[429])
        api_simulee(fausse).lire({"limit": 1})
        self.assertEqual(self.pauses[0], 0.0)  # Retry-After: 0, pas 0,5 s

    def test_wraps_garde_le_nom(self) -> None:
        self.assertEqual(Api.lire.__name__, "lire")


class DebitTests(unittest.TestCase):
    def test_intervalle_minimal(self) -> None:
        debit = Debit(par_seconde=20)
        import time

        depart = time.monotonic()
        for _ in range(5):
            debit.attendre()
        self.assertGreaterEqual(time.monotonic() - depart, 4 * 0.05 * 0.95)


class IngestionTests(SansDormir):
    def test_mur(self) -> None:
        api = api_simulee(FausseApi(fausse_base()))
        self.assertEqual(trouver_mur(api, limite=100), 9_900)
        self.assertEqual(trouver_mur(api, limite=1), 9_999)

    def test_ingestion_complete_et_idempotente(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dossier = Path(tmp)
            bilan = ingerer(api_simulee(FausseApi(fausse_base())), dossier)
            self.assertEqual(bilan.lignes_sur_disque, 252)
            self.assertEqual(bilan.ecrites, 4)
            self.assertTrue((dossier / "dep=059.parquet").exists())
            self.assertTrue((dossier / "dep=inconnu.parquet").exists())
            self.assertEqual(list(dossier.glob("*.partiel")), [])

            fausse = FausseApi(fausse_base())
            bilan = ingerer(api_simulee(fausse), dossier)
            self.assertEqual((bilan.ecrites, bilan.sautees), (0, 4))
            self.assertEqual(bilan.lignes_sur_disque, 252)

    def test_garde_fou_liste_de_partitions_tronquee(self) -> None:
        # Le serveur ne renvoie que 2 groupes par page : si on ne paginait pas la
        # liste, des départements disparaîtraient. Ici on la pagine : tout passe.
        with tempfile.TemporaryDirectory() as tmp:
            fausse = FausseApi(fausse_base(), groupes_par_page_max=2)
            with mock.patch.object(ingestion, "TAILLE_PAGE", 2):
                bilan = ingerer(api_simulee(fausse), Path(tmp))
            self.assertEqual(bilan.lignes_sur_disque, 252)

    def test_garde_fou_arrete_si_somme_differe(self) -> None:
        with self.assertRaises(IngestionIncomplete):
            ingestion.verifier_partitions({"001": 10, "059": 5}, total=20)

    def test_reprise_apres_interruption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dossier = Path(tmp)
            vraie = ingestion.lire_partition
            appels = 0

            def interrompue(*args: Any) -> Any:
                nonlocal appels
                appels += 1
                if appels == 3:
                    raise KeyboardInterrupt
                return vraie(*args)

            with mock.patch.object(ingestion, "lire_partition", interrompue):
                with self.assertRaises(KeyboardInterrupt):
                    ingerer(api_simulee(FausseApi(fausse_base())), dossier)
            self.assertEqual(len(list(dossier.glob("dep=*.parquet"))), 2)

            bilan = ingerer(api_simulee(FausseApi(fausse_base())), dossier)
            self.assertEqual((bilan.ecrites, bilan.sautees), (2, 2))
            self.assertEqual(bilan.lignes_sur_disque, 252)

    def test_ecriture_atomique(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cible = Path(tmp) / "dep=059.parquet"

            def coupure(self: pd.DataFrame, chemin: Path, **_: Any) -> None:
                Path(chemin).write_bytes(b"PAR1 tronque")
                raise KeyboardInterrupt

            with mock.patch.object(pd.DataFrame, "to_parquet", coupure):
                with self.assertRaises(KeyboardInterrupt):
                    ingestion.ecrire_atomique([{"a": 1}], cible)
            self.assertFalse(cible.exists())  # la reprise ne le sautera pas


class RelectureEtCleTests(SansDormir):
    def test_lecteur_partitions_et_cle(self) -> None:
        from annuaire.analyse import analyser_cle
        from annuaire.lecture import LecteurPartitions, charger_partitions

        base = fausse_base()
        base.append(dict(base[0], multi_uai=True))  # la source renvoie un doublon
        with tempfile.TemporaryDirectory() as tmp:
            dossier = Path(tmp)
            ingerer(api_simulee(FausseApi(base)), dossier)
            self.assertEqual(len(list(LecteurPartitions(dossier).lire())), 253)
            resultat = analyser_cle(charger_partitions(dossier))
        self.assertEqual((resultat.lignes, resultat.identifiants_distincts), (253, 252))
        self.assertEqual(resultat.identifiants_en_double, 1)
        self.assertEqual(resultat.doublons_meme_partition, 1)


if __name__ == "__main__":
    unittest.main()
