"""Módulo de inyección de defectos de calidad de datos para transportadoras Tipo C (Sección 5.3).

Implementa los 5 tipos de anomalías deliberadas:
1. Guías inexistentes (fuera del universo WMS).
2. Eventos fuera de secuencia temporal.
3. Formatos de fecha mezclados (DD/MM/YYYY HH:MM vs MM/DD/YYYY HH:MM).
4. Filas basura y encabezados repetidos (totales al pie, cabeceras intermedias).
5. Filas duplicadas.
"""

from copy import deepcopy
from datetime import datetime
import random
from typing import Any, Dict, List


def inject_nonexistent_guides(
    rows: List[Dict[str, Any]],
    tracking_col: str,
    rng: random.Random,
    error_rate: float,
) -> List[Dict[str, Any]]:
    """Inyecta números de guía ficticios que no existen en el WMS."""
    if not rows or error_rate <= 0:
        return rows

    result = deepcopy(rows)
    target_count = max(1, int(len(result) * error_rate))
    indices_to_corrupt = rng.sample(range(len(result)), min(target_count, len(result)))

    for idx in indices_to_corrupt:
        fake_id = rng.randint(900000, 999999)
        result[idx][tracking_col] = f"FAKE_WAYBILL_{fake_id}"

    return result


def inject_out_of_sequence_events(
    rows: List[Dict[str, Any]],
    tracking_col: str,
    status_col: str,
    timestamp_col: str,
    rng: random.Random,
    error_rate: float,
) -> List[Dict[str, Any]]:
    """Genera eventos fuera de secuencia temporal (ej. entregado antes de tránsito o timestamps invertidos)."""
    if not rows or error_rate <= 0:
        return rows

    result = deepcopy(rows)

    # Agrupar índices por tracking_col
    guides_map: Dict[str, List[int]] = {}
    for idx, row in enumerate(result):
        guide = str(row.get(tracking_col, ""))
        guides_map.setdefault(guide, []).append(idx)

    # Filtrar guías con al menos 2 eventos para invertir temporalmente
    candidates = [indices for indices in guides_map.values() if len(indices) >= 2]
    if not candidates:
        return result

    target_count = max(1, int(len(candidates) * error_rate))
    selected_groups = rng.sample(candidates, min(target_count, len(candidates)))

    for group in selected_groups:
        # Tomar dos eventos dentro del grupo y swappear sus marcas de tiempo
        i, j = rng.sample(group, 2)
        ts_i = result[i][timestamp_col]
        ts_j = result[j][timestamp_col]
        result[i][timestamp_col] = ts_j
        result[j][timestamp_col] = ts_i

    return result


def inject_mixed_date_formats(
    rows: List[Dict[str, Any]],
    timestamp_col: str,
    rng: random.Random,
    error_rate: float,
) -> List[Dict[str, Any]]:
    """Intercala formatos de fecha ambiguos: DD/MM/YYYY HH:MM y MM/DD/YYYY HH:MM."""
    if not rows or error_rate <= 0:
        return rows

    result = deepcopy(rows)
    target_count = max(1, int(len(result) * error_rate))
    indices_to_corrupt = rng.sample(range(len(result)), min(target_count, len(result)))

    for idx in indices_to_corrupt:
        raw_val = result[idx].get(timestamp_col)
        # Parsear datetime si viene en formato estándar
        dt: datetime
        if isinstance(raw_val, datetime):
            dt = raw_val
        elif isinstance(raw_val, str):
            try:
                dt = datetime.fromisoformat(raw_val)
            except ValueError:
                continue
        else:
            continue

        # Decidir aleatoriamente entre DD/MM/YYYY y MM/DD/YYYY
        if rng.random() < 0.5:
            # Formato latino/europeo
            result[idx][timestamp_col] = dt.strftime("%d/%m/%Y %H:%M")
        else:
            # Formato anglosajón
            result[idx][timestamp_col] = dt.strftime("%m/%d/%Y %H:%M")

    return result


def inject_duplicate_rows(
    rows: List[Dict[str, Any]],
    rng: random.Random,
    error_rate: float,
) -> List[Dict[str, Any]]:
    """Duplica registros completos dentro de la lista de eventos."""
    if not rows or error_rate <= 0:
        return rows

    result = deepcopy(rows)
    target_count = max(1, int(len(rows) * error_rate))
    indices_to_duplicate = rng.sample(range(len(rows)), min(target_count, len(rows)))

    for idx in indices_to_duplicate:
        duplicate_item = deepcopy(rows[idx])
        # Insertar en una posición aleatoria
        insert_pos = rng.randint(0, len(result))
        result.insert(insert_pos, duplicate_item)

    return result


def inject_header_and_summary_rows(
    rows: List[Dict[str, Any]],
    columns: List[str],
    rng: random.Random,
    error_rate: float,
) -> List[Dict[str, Any]]:
    """Inserta filas intermedias repetidas con el encabezado y filas de pie/resumen (ej. TOTAL REGISTROS: N)."""
    if not rows or error_rate <= 0:
        return rows

    result = deepcopy(rows)

    # 1. Inserción de cabeceras intermedias repetidas
    num_headers = max(1, int(len(result) * (error_rate * 0.5)))
    for _ in range(num_headers):
        if len(result) < 3:
            break
        # Crear un registro donde cada columna tiene el nombre de la propia columna
        repeated_header = {col: col for col in columns}
        insert_pos = rng.randint(1, len(result) - 1)
        result.insert(insert_pos, repeated_header)

    # 2. Inserción de filas de pie con resumen o totales
    summary_row = {col: "" for col in columns}
    primary_col = columns[0]
    secondary_col = columns[1] if len(columns) > 1 else primary_col
    summary_row[primary_col] = f"TOTAL REGISTROS: {len(rows)}"
    summary_row[secondary_col] = "--- FIN DE LOTE ---"

    result.append(summary_row)

    return result


def apply_all_corruptions(
    rows: List[Dict[str, Any]],
    columns: List[str],
    tracking_col: str,
    status_col: str,
    timestamp_col: str,
    rng: random.Random,
    error_rate: float,
) -> List[Dict[str, Any]]:
    """Aplica de forma orquestada y determinista los 5 tipos de defectos según el error_rate."""
    if error_rate <= 0.0:
        return rows

    # 1. Guías inexistentes
    step1 = inject_nonexistent_guides(rows, tracking_col, rng, error_rate)

    # 2. Eventos fuera de secuencia temporal
    step2 = inject_out_of_sequence_events(step1, tracking_col, status_col, timestamp_col, rng, error_rate)

    # 3. Formatos de fecha mezclados
    step3 = inject_mixed_date_formats(step2, timestamp_col, rng, error_rate)

    # 4. Filas duplicadas
    step4 = inject_duplicate_rows(step3, rng, error_rate)

    # 5. Cabeceras repetidas y filas de totales/resumen
    final_rows = inject_header_and_summary_rows(step4, columns, rng, error_rate)

    return final_rows
