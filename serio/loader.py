# loader.py
"""
Motor de carga de datos y simulación.
Encapsula toda la lógica matemática del modelo Leontief regionalizado.
"""
import os, json
import numpy as np
import pandas as pd


# ── Conversión de unidades ─────────────────────────────────────────────────────
# Las matrices X, Z, Y, v·X, e·X están en millones de pesos (Mmdp = Mdp).
# El usuario introduce shocks en pesos (MXN). Factor de conversión:
MXN_A_MMDP = 1 / 1_000_000   # 1 peso = 1e-6 Mmdp

# Nombre legible de cada estado
def _nombre_estado(key: str) -> str:
    mapping = {"CDMX": "Ciudad de México"}
    if key in mapping:
        return mapping[key]
    return key.replace("_", " ").title()


class ModeloEconomico:
    """
    Carga el output del pipeline de regionalización FLQ+RAS y provee
    tres tipos de simulación de shock de demanda final:
      - Producción  (ΔX  = L @ ΔY)
      - Ingreso/VA  (ΔVA = v * ΔX)
      - Empleo      (ΔE  = e * ΔX)
    """

    def __init__(self, data_path: str):
        self.path = data_path

        # ── Metadatos ──────────────────────────────────────────────────────
        with open(os.path.join(data_path, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
        self.sectores: list[str]      = meta["sectores"]          # códigos SCIAN
        self.sector_names: dict       = meta["sector_names"]      # código → nombre
        self.n: int                   = len(self.sectores)

        # ── Índice SCIAN → posición ────────────────────────────────────────
        self.scian_idx: dict[str, int] = {s: i for i, s in enumerate(self.sectores)}

        # ── Sectores (DataFrame para UI) ──────────────────────────────────
        self.df_sectores = pd.read_csv(
            os.path.join(data_path, "sectores.csv"), encoding="utf-8"
        )

        # ── Resumen por estado ────────────────────────────────────────────
        self.df_resumen = pd.read_json(
            os.path.join(data_path, "resumen.json"), encoding="utf-8"
        )

        # ── Lista de estados disponibles ──────────────────────────────────
        self.estados_raw: list[str] = sorted([
            d for d in os.listdir(data_path)
            if os.path.isdir(os.path.join(data_path, d))
            and os.path.exists(os.path.join(data_path, d, "L.npy"))
        ])

        # mapa nombre legible → clave de carpeta
        self.mapa_estados: dict[str, str] = {
            _nombre_estado(e): e for e in self.estados_raw
        }

        # ── Matrices nacionales ────────────────────────────────────────────
        self.X_n = np.load(os.path.join(data_path, "X_nacional.npy"))
        self.A_n = np.load(os.path.join(data_path, "A_nacional.npy"))

        # Coeficiente de valor agregado nacional: v_n_j = 1 - sum_i(A_n_ij)
        # Justificación: X_r = va_r por construcción del proxy, así v = VA/X = 1
        # siempre (sin información). La alternativa correcta es la estructura de
        # VA de la MIP nacional: v_n = 1 - col_sum(A_n).
        self.v_n: np.ndarray = np.clip(1.0 - self.A_n.sum(axis=0), 0.0, 1.0)

        # ── Caché en memoria ──────────────────────────────────────────────
        self._cache: dict[str, dict] = {}

    # ── Carga de estado ───────────────────────────────────────────────────────
    def _load_estado(self, estado_key: str) -> dict:
        """Carga todas las matrices del estado (con caché en memoria)."""
        if estado_key in self._cache:
            return self._cache[estado_key]

        p = os.path.join(self.path, estado_key)

        data = {
            "X":    np.load(os.path.join(p, "X.npy")),      # producción (Mmdp)
            "Y":    np.load(os.path.join(p, "Y.npy")),      # demanda final (Mmdp)
            "L":    np.load(os.path.join(p, "L.npy")),      # inversa Leontief
            "v":    np.load(os.path.join(p, "v.npy")),      # coef. valor agregado [0,1]
            "e":    np.load(os.path.join(p, "e.npy")),      # coef. empleo (puestos/Mmdp)
            "VA_r": np.load(os.path.join(p, "VA_r.npy")),   # VA real (Mmdp)
            "PO_r": np.load(os.path.join(p, "PO_r.npy")),   # personal ocupado
            "A":    np.load(os.path.join(p, "A.npy")),      # coef. técnicos
            "FLQ":  np.load(os.path.join(p, "FLQ.npy")),    # matriz FLQ
        }
        self._cache[estado_key] = data
        return data

    # ── Información de un estado ──────────────────────────────────────────────
    def info_estado(self, estado_key: str) -> dict:
        """Devuelve estadísticas descriptivas del estado."""
        d = self._load_estado(estado_key)
        res = self.df_resumen[self.df_resumen["estado"] == estado_key]
        meta_row = res.iloc[0].to_dict() if not res.empty else {}
        return {
            "X_total_mmdp":   float(d["X"].sum()),
            "VA_total_mmdp":  float(d["VA_r"].sum()),
            "PO_total":       int(d["PO_r"].sum()),
            "sectores_activos": int((d["VA_r"] > 0).sum()),
            "mult_promedio":  meta_row.get("mult_promedio", None),
        }

    # ── Simulación principal ──────────────────────────────────────────────────
    def simular(
        self,
        estado_key: str,
        sector_idx: int,
        monto_pesos: float,
    ) -> dict:
        """
        Simula un shock de demanda final en un sector específico.

        Parámetros:
          estado_key  : clave interna del estado (p.ej. "AGUASCALIENTES")
          sector_idx  : posición en el vector (0..n-1)
          monto_pesos : shock en pesos mexicanos (positivo = expansión)

        Retorna dict con:
          delta_X, delta_VA, delta_E  (arrays de longitud n)
          mult_produccion, mult_ingreso, mult_empleo  (escalares)
          df_detalle  (DataFrame ordenado, listo para visualización)
        """
        if not (0 <= sector_idx < self.n):
            raise ValueError(f"Sector {sector_idx} fuera de rango [0, {self.n-1}]")

        d = self._load_estado(estado_key)
        L, e, X = d["L"], d["e"], d["X"]
        #v = self.v_n   coeficiente VA nacional (v estatal = 1 por construcción)
        v = d["v"]

        # Convertir pesos a Mmdp (unidad del modelo)
        monto_mmdp = monto_pesos * MXN_A_MMDP

        # Vector de shock
        delta_Y = np.zeros(self.n)
        delta_Y[sector_idx] = monto_mmdp

        # ── Impactos ─────────────────────────────────────────────────────
        delta_X  = L @ delta_Y            # producción total (Mmdp)
        delta_VA = v * delta_X            # valor agregado (Mmdp)
        delta_E  = e * delta_X            # empleo (puestos)

        # ── Multiplicadores ───────────────────────────────────────────────
        mult_prod    = delta_X.sum()  / monto_mmdp if monto_mmdp != 0 else 0
        mult_ingreso = delta_VA.sum() / monto_mmdp if monto_mmdp != 0 else 0
        # Multiplicador de empleo: puestos por millón de pesos invertido
        # e_j está en puestos/Mmdp; monto_mmdp en millones de pesos
        # → mult_empleo = puestos totales / millones de pesos = puestos/Mmdp
        mult_empleo  = delta_E.sum()  / monto_mmdp if monto_mmdp != 0 else 0

        # ── DataFrame detalle ─────────────────────────────────────────────
        df = pd.DataFrame({
            "indice":    np.arange(self.n),
            "scian":     self.sectores,
            "nombre":    [self.sector_names[s] for s in self.sectores],
            "base_mmdp": X,
            "base_pesos": X / MXN_A_MMDP,
            "activo":    d["VA_r"] > 0,
            "delta_X_mmdp":   delta_X,
            "delta_X_pesos":  delta_X / MXN_A_MMDP,
            "delta_VA_mmdp":  delta_VA,
            "delta_VA_pesos": delta_VA / MXN_A_MMDP,
            "delta_E":        delta_E,
            "v_j":       v,
            "e_j":       e,
        })

        df["variacion_pct"] = np.where(
            df["base_mmdp"] > 1e-6,
            df["delta_X_mmdp"] / df["base_mmdp"] * 100,
            np.nan,
        )

        total_delta_X = delta_X.sum()
        df["share_produccion"] = np.where(
            total_delta_X != 0,
            df["delta_X_mmdp"] / total_delta_X,
            0.0,
        )

        # FIX: sort by absolute value so negative shocks show largest contractions
        #      first (ascending=False on raw value was showing near-zero sectors at top)
        df["_abs_delta_X"] = df["delta_X_pesos"].abs()
        df = df.sort_values("_abs_delta_X", ascending=False).drop(columns=["_abs_delta_X"]).reset_index(drop=True)

        return {
            "delta_X":       delta_X,
            "delta_VA":      delta_VA,
            "delta_E":       delta_E,
            "delta_X_total_pesos":   float(delta_X.sum() / MXN_A_MMDP),
            "delta_VA_total_pesos":  float(delta_VA.sum() / MXN_A_MMDP),
            "delta_E_total":         float(delta_E.sum()),
            "monto_mmdp":            monto_mmdp,
            "monto_pesos":           monto_pesos,
            "mult_produccion":       float(mult_prod),
            "mult_ingreso":          float(mult_ingreso),
            "mult_empleo":           float(mult_empleo),
            "df_detalle":            df,
            "sector_base_pesos":     float(X[sector_idx] / MXN_A_MMDP),
        }

    # ── Comparación entre estados ─────────────────────────────────────────────
    def comparar_estados(
        self,
        sector_idx: int,
        monto_pesos: float,
    ) -> pd.DataFrame:
        """
        Corre la misma simulación en todos los estados y devuelve
        un DataFrame comparativo.
        """
        filas = []
        for key in self.estados_raw:
            d = self._load_estado(key)
            if d["VA_r"][sector_idx] <= 0:
                continue   # sector inactivo en este estado
            res = self.simular(key, sector_idx, monto_pesos)
            filas.append({
                "estado":            _nombre_estado(key),
                "estado_key":        key,
                "mult_produccion":   res["mult_produccion"],
                "mult_ingreso":      res["mult_ingreso"],
                "mult_empleo_1M":    res["mult_empleo"] * 1_000_000,  # puestos por 1M pesos
                "delta_X_pesos":     res["delta_X_total_pesos"],
                "delta_VA_pesos":    res["delta_VA_total_pesos"],
                "delta_E":           res["delta_E_total"],
            })
        return pd.DataFrame(filas).sort_values("mult_produccion", ascending=False)

    # ── Top sectores por multiplicador ────────────────────────────────────────
    def top_multiplicadores(self, estado_key: str, top_n: int = 10) -> pd.DataFrame:
        """Ranking de sectores por multiplicador de producción en un estado."""
        d = self._load_estado(estado_key)
        L = d["L"]
        mult = L.sum(axis=0)   # multiplicador de producción por sector
        df = pd.DataFrame({
            "scian":   self.sectores,
            "nombre":  [self.sector_names[s] for s in self.sectores],
            "mult":    mult,
            "activo":  d["VA_r"] > 0,
            "X_mmdp":  d["X"],
        })
        return (
            df[df["activo"]]
            .sort_values("mult", ascending=False)
            .head(top_n)
            .reset_index(drop=True)
        )
