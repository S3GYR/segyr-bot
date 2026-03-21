from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

import psycopg
from psycopg import rows

from config.settings import settings


class MemoryStore:
    """Stockage structuré sur PostgreSQL (clients, projets, historiques)."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = (dsn or settings.postgres_dsn).replace("postgresql+psycopg", "postgresql")
        self._schema_ready = False

    def _connect(self):
        conn = psycopg.connect(self.dsn, autocommit=True, row_factory=rows.dict_row)
        if not self._schema_ready:
            self._ensure_schema(conn)
            self._schema_ready = True
        return conn

    def _ensure_schema(self, conn) -> None:
        ddl_statements = [
            """
            CREATE TABLE IF NOT EXISTS clients (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT,
                phone TEXT,
                notes TEXT,
                score_client INTEGER DEFAULT 50,
                entreprise_id TEXT,
                created_at TIMESTAMPTZ DEFAULT now()
            );
            ALTER TABLE clients ADD COLUMN IF NOT EXISTS score_client INTEGER DEFAULT 50;
            ALTER TABLE clients ADD COLUMN IF NOT EXISTS entreprise_id TEXT;
            """,
            """
            CREATE TABLE IF NOT EXISTS factures (
                id SERIAL PRIMARY KEY,
                client_id INTEGER,
                entreprise_id TEXT,
                montant_ht NUMERIC,
                due_date DATE,
                statut TEXT DEFAULT 'brouillon',
                reference TEXT,
                notes TEXT,
                created_at TIMESTAMPTZ DEFAULT now()
            );
            ALTER TABLE factures ADD COLUMN IF NOT EXISTS entreprise_id TEXT;
            """,
            """
            CREATE TABLE IF NOT EXISTS projets (
                id SERIAL PRIMARY KEY,
                titre TEXT NOT NULL,
                client_id INTEGER,
                entreprise_id TEXT,
                numero_affaire TEXT,
                montant_ht NUMERIC,
                echeance DATE,
                statut TEXT DEFAULT 'brouillon',
                avancement NUMERIC DEFAULT 0,
                risk_score INTEGER DEFAULT 0,
                heures_vendues NUMERIC DEFAULT 0,
                heures_consommees NUMERIC DEFAULT 0,
                heures_restantes NUMERIC DEFAULT 0,
                reste_a_faire NUMERIC DEFAULT 0,
                derive_heures NUMERIC DEFAULT 0,
                derive_pourcentage NUMERIC DEFAULT 0,
                budget_materiel_prevu NUMERIC DEFAULT 0,
                budget_materiel_engage NUMERIC DEFAULT 0,
                budget_materiel_restant NUMERIC DEFAULT 0,
                derive_budget_materiel NUMERIC DEFAULT 0,
                derive_budget_pourcentage NUMERIC DEFAULT 0,
                notes TEXT,
                created_at TIMESTAMPTZ DEFAULT now()
            );
            ALTER TABLE projets ADD COLUMN IF NOT EXISTS risk_score INTEGER DEFAULT 0;
            ALTER TABLE projets ADD COLUMN IF NOT EXISTS heures_vendues NUMERIC DEFAULT 0;
            ALTER TABLE projets ADD COLUMN IF NOT EXISTS heures_consommees NUMERIC DEFAULT 0;
            ALTER TABLE projets ADD COLUMN IF NOT EXISTS heures_restantes NUMERIC DEFAULT 0;
            ALTER TABLE projets ADD COLUMN IF NOT EXISTS reste_a_faire NUMERIC DEFAULT 0;
            ALTER TABLE projets ADD COLUMN IF NOT EXISTS derive_heures NUMERIC DEFAULT 0;
            ALTER TABLE projets ADD COLUMN IF NOT EXISTS derive_pourcentage NUMERIC DEFAULT 0;
            ALTER TABLE projets ADD COLUMN IF NOT EXISTS budget_materiel_prevu NUMERIC DEFAULT 0;
            ALTER TABLE projets ADD COLUMN IF NOT EXISTS budget_materiel_engage NUMERIC DEFAULT 0;
            ALTER TABLE projets ADD COLUMN IF NOT EXISTS budget_materiel_restant NUMERIC DEFAULT 0;
            ALTER TABLE projets ADD COLUMN IF NOT EXISTS derive_budget_materiel NUMERIC DEFAULT 0;
            ALTER TABLE projets ADD COLUMN IF NOT EXISTS derive_budget_pourcentage NUMERIC DEFAULT 0;
            ALTER TABLE projets ADD COLUMN IF NOT EXISTS entreprise_id TEXT;
            ALTER TABLE projets ADD COLUMN IF NOT EXISTS numero_affaire TEXT;
            """,
            """
            CREATE TABLE IF NOT EXISTS fdv_history (
                id SERIAL PRIMARY KEY,
                chantier_id TEXT NOT NULL,
                date_snapshot TIMESTAMPTZ DEFAULT now(),
                cout_direct NUMERIC,
                prix_revient NUMERIC,
                marge NUMERIC,
                rentabilite NUMERIC,
                heures_consommees NUMERIC,
                materiel_reel NUMERIC
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS conversation_history (
                id SERIAL PRIMARY KEY,
                user_id TEXT,
                role TEXT,
                content TEXT,
                created_at TIMESTAMPTZ DEFAULT now()
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS decision_history (
                id SERIAL PRIMARY KEY,
                user_id TEXT,
                intents JSONB,
                decision JSONB,
                actions JSONB,
                created_at TIMESTAMPTZ DEFAULT now()
            );
            """,
        ]
        with conn.cursor() as cur:
            for ddl in ddl_statements:
                cur.execute(ddl)

    def _cleanup_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        clean: Dict[str, Any] = {}
        for k, v in row.items():
            if isinstance(v, Decimal):
                clean[k] = float(v)
            elif isinstance(v, (datetime, date)):
                clean[k] = v.isoformat()
            else:
                clean[k] = v
        return clean

    def raw_query(self, sql_query: str, params: Iterable[Any] | None = None) -> List[Dict[str, Any]]:
        if not sql_query.lower().strip().startswith("select"):
            raise ValueError("Seules les requêtes SELECT sont autorisées via raw_query")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_query, params or [])
                rows_data = cur.fetchall()
        return [self._cleanup_row(r) for r in rows_data]

    # Clients
    def add_client(self, name: str, email: str | None = None, phone: str | None = None, notes: str | None = None, score_client: int | None = None, entreprise_id: str | None = None) -> Dict[str, Any]:
        query = "INSERT INTO clients (name, email, phone, notes, score_client, entreprise_id) VALUES (%s, %s, %s, %s, %s, %s) RETURNING *"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (name, email, phone, notes, score_client if score_client is not None else 50, entreprise_id))
                row = cur.fetchone()
        return self._cleanup_row(row)

    def list_clients(self, entreprise_id: str | None = None) -> List[Dict[str, Any]]:
        if entreprise_id:
            rows_data = self.raw_query("SELECT * FROM clients WHERE entreprise_id = %s ORDER BY id DESC", (entreprise_id,))
        else:
            rows_data = self.raw_query("SELECT * FROM clients ORDER BY id DESC")
        return rows_data

    def get_client(self, client_id: int) -> Optional[Dict[str, Any]]:
        results = self.raw_query("SELECT * FROM clients WHERE id = %s", (client_id,))
        return results[0] if results else None

    def update_client(self, client_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not data:
            return self.get_client(client_id)
        columns = list(data.keys())
        values = list(data.values())
        set_clause = ", ".join(f"{col} = %s" for col in columns)
        query = f"UPDATE clients SET {set_clause} WHERE id = %s RETURNING *"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (*values, client_id))
                row = cur.fetchone()
        return self._cleanup_row(row) if row else None

    def update_client_score(self, client_id: int, score: float) -> Optional[Dict[str, Any]]:
        return self.update_client(client_id, {"score_client": score})

    # Factures
    def add_facture(self, client_id: int | None, montant_ht: float, due_date: str | None, reference: str | None, notes: str | None, entreprise_id: str | None = None) -> Dict[str, Any]:
        query = """
        INSERT INTO factures (client_id, entreprise_id, montant_ht, due_date, reference, notes)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING *
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (client_id, entreprise_id, montant_ht, due_date, reference, notes))
                row = cur.fetchone()
        return self._cleanup_row(row)

    def list_factures(self, entreprise_id: str | None = None) -> List[Dict[str, Any]]:
        if entreprise_id:
            return self.raw_query("SELECT * FROM factures WHERE entreprise_id = %s ORDER BY id DESC", (entreprise_id,))
        return self.raw_query("SELECT * FROM factures ORDER BY id DESC")

    def get_unpaid_client_invoices(self, entreprise_id: str | None = None) -> List[Dict[str, Any]]:
        if entreprise_id:
            return self.raw_query(
                "SELECT * FROM factures WHERE entreprise_id = %s AND (statut IS NULL OR (statut NOT IN ('payée','paye') AND statut <> 'fournisseur_impayee'))",
                (entreprise_id,),
            )
        return self.raw_query("SELECT * FROM factures WHERE statut IS NULL OR (statut NOT IN ('payée','paye') AND statut <> 'fournisseur_impayee')")

    def get_unpaid_supplier_invoices(self, entreprise_id: str | None = None) -> List[Dict[str, Any]]:
        # Placeholder: suppliers not modelled; reuse factures with negative client_id marker or statut fournisseur
        if entreprise_id:
            return self.raw_query(
                "SELECT * FROM factures WHERE entreprise_id = %s AND statut = 'fournisseur_impayee'",
                (entreprise_id,),
            )
        return self.raw_query("SELECT * FROM factures WHERE statut = 'fournisseur_impayee'")

    def list_factures_by_client(self, client_id: int, entreprise_id: str | None = None) -> List[Dict[str, Any]]:
        if entreprise_id:
            return self.raw_query(
                "SELECT * FROM factures WHERE client_id = %s AND entreprise_id = %s",
                (client_id, entreprise_id),
            )
        return self.raw_query("SELECT * FROM factures WHERE client_id = %s", (client_id,))

    def get_facture(self, facture_id: int) -> Optional[Dict[str, Any]]:
        results = self.raw_query("SELECT * FROM factures WHERE id = %s", (facture_id,))
        return results[0] if results else None

    def update_facture(self, facture_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not data:
            return self.get_facture(facture_id)
        columns = list(data.keys())
        values = list(data.values())
        set_clause = ", ".join(f"{col} = %s" for col in columns)
        query = f"UPDATE factures SET {set_clause} WHERE id = %s RETURNING *"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (*values, facture_id))
                row = cur.fetchone()
        return self._cleanup_row(row) if row else None

    # Projets / chantiers / affaires
    def add_project(
        self,
        titre: str,
        client_id: int | None,
        entreprise_id: str | None = None,
        numero_affaire: str | None = None,
        montant_ht: float | None = None,
        echeance: str | None = None,
        statut: str = "brouillon",
        avancement: float = 0.0,
        notes: str | None = None,
        risk_score: int = 0,
        heures_vendues: float = 0.0,
        heures_consommees: float = 0.0,
        heures_restantes: float = 0.0,
        reste_a_faire: float = 0.0,
        derive_heures: float = 0.0,
        derive_pourcentage: float = 0.0,
        budget_materiel_prevu: float = 0.0,
        budget_materiel_engage: float = 0.0,
        budget_materiel_restant: float = 0.0,
        derive_budget_materiel: float = 0.0,
        derive_budget_pourcentage: float = 0.0,
    ) -> Dict[str, Any]:
        query = """
        INSERT INTO projets (titre, client_id, entreprise_id, numero_affaire, montant_ht, echeance, statut, avancement, notes, risk_score,
                             heures_vendues, heures_consommees, heures_restantes, reste_a_faire, derive_heures, derive_pourcentage,
                             budget_materiel_prevu, budget_materiel_engage, budget_materiel_restant, derive_budget_materiel, derive_budget_pourcentage)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query,
                    (
                        titre,
                        client_id,
                        entreprise_id,
                        numero_affaire,
                        montant_ht,
                        echeance,
                        statut,
                        avancement,
                        notes,
                        risk_score,
                        heures_vendues,
                        heures_consommees,
                        heures_restantes,
                        reste_a_faire,
                        derive_heures,
                        derive_pourcentage,
                        budget_materiel_prevu,
                        budget_materiel_engage,
                        budget_materiel_restant,
                        derive_budget_materiel,
                        derive_budget_pourcentage,
                    ),
                )
                row = cur.fetchone()
        return self._cleanup_row(row)

    def list_projects(self, entreprise_id: str | None = None) -> List[Dict[str, Any]]:
        if entreprise_id:
            return self.raw_query("SELECT * FROM projets WHERE entreprise_id = %s ORDER BY id DESC", (entreprise_id,))
        return self.raw_query("SELECT * FROM projets ORDER BY id DESC")

    def get_project(self, project_id: int) -> Optional[Dict[str, Any]]:
        results = self.raw_query("SELECT * FROM projets WHERE id = %s", (project_id,))
        return results[0] if results else None

    def update_project(self, project_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not data:
            return self.get_project(project_id)
        columns = list(data.keys())
        values = list(data.values())
        set_clause = ", ".join(f"{col} = %s" for col in columns)
        query = f"UPDATE projets SET {set_clause} WHERE id = %s RETURNING *"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (*values, project_id))
                row = cur.fetchone()
        return self._cleanup_row(row) if row else None

    # Entreprises
    def add_enterprise(self, name: str) -> Dict[str, Any]:
        import uuid

        ent_id = str(uuid.uuid4())
        query = "INSERT INTO entreprises (id, name) VALUES (%s, %s) RETURNING *"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (ent_id, name))
                row = cur.fetchone()
        return self._cleanup_row(row)

    def list_enterprises(self) -> List[Dict[str, Any]]:
        return self.raw_query("SELECT * FROM entreprises ORDER BY created_at DESC")

    def get_enterprise(self, ent_id: str) -> Optional[Dict[str, Any]]:
        rows_data = self.raw_query("SELECT * FROM entreprises WHERE id = %s", (ent_id,))
        return rows_data[0] if rows_data else None

    # Users
    def add_user(self, email: str, password_hash: str, role: str, entreprise_id: str) -> Dict[str, Any]:
        import uuid

        user_id = str(uuid.uuid4())
        query = "INSERT INTO users (id, email, password_hash, role, entreprise_id) VALUES (%s, %s, %s, %s, %s) RETURNING *"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (user_id, email, password_hash, role, entreprise_id))
                row = cur.fetchone()
        return self._cleanup_row(row)

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        rows_data = self.raw_query("SELECT * FROM users WHERE email = %s", (email,))
        return rows_data[0] if rows_data else None

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        rows_data = self.raw_query("SELECT * FROM users WHERE id = %s", (user_id,))
        return rows_data[0] if rows_data else None

    def list_users(self, entreprise_id: str | None = None) -> List[Dict[str, Any]]:
        if entreprise_id:
            return self.raw_query("SELECT * FROM users WHERE entreprise_id = %s ORDER BY created_at DESC", (entreprise_id,))
        return self.raw_query("SELECT * FROM users ORDER BY created_at DESC")

    # FDV history
    def save_fdv_snapshot(self, data: Dict[str, Any]) -> Dict[str, Any]:
        chantier_id = str(data.get("chantier_id"))
        if not chantier_id:
            raise ValueError("chantier_id requis pour fdv_history")
        query = """
        INSERT INTO fdv_history (chantier_id, cout_direct, prix_revient, marge, rentabilite, heures_consommees, materiel_reel)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """
        values = (
            chantier_id,
            data.get("cout_direct"),
            data.get("prix_revient"),
            data.get("marge"),
            data.get("rentabilite") or data.get("rentabilite_pct"),
            data.get("heures_consommees"),
            data.get("materiel_reel") or data.get("budget_materiel_engage"),
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)
                row = cur.fetchone()
        return self._cleanup_row(row) if row else {}

    def get_fdv_history(self, chantier_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        results = self.raw_query(
            "SELECT * FROM fdv_history WHERE chantier_id = %s ORDER BY date_snapshot DESC LIMIT %s",
            (str(chantier_id), limit),
        )
        return results

    # Historique conversation
    def add_history(self, user_id: str, role: str, content: str) -> None:
        query = "INSERT INTO conversation_history (user_id, role, content) VALUES (%s, %s, %s)"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (user_id, role, content))

    def get_history(self, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        results = self.raw_query(
            "SELECT role, content, created_at FROM conversation_history WHERE user_id = %s ORDER BY id DESC LIMIT %s",
            (user_id, limit),
        )
        return results[::-1]

    # Decision history
    def add_decision(self, user_id: str, intents: List[Dict[str, Any]], decision: Dict[str, Any], actions: List[Dict[str, Any]] | List[str] | None = None) -> None:
        query = "INSERT INTO decision_history (user_id, intents, decision, actions) VALUES (%s, %s, %s, %s)"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (user_id, intents, decision, actions or []))

    def get_decisions(self, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        results = self.raw_query(
            "SELECT intents, decision, actions, created_at FROM decision_history WHERE user_id = %s ORDER BY id DESC LIMIT %s",
            (user_id, limit),
        )
        return results[::-1]
