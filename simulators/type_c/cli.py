"""CLI para ejecutar el simulador de transportadoras Tipo C con inyección de defectos."""

import argparse
from pathlib import Path
import sys

from simulators.type_c.catalogs import CARRIERS_REGISTRY, get_carrier_config
from simulators.type_c.generator import TypeCSimulator, compute_file_sha256


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulador de Archivos Tipo C (Transportadoras en Lote) con Inyección de Defectos (F5, Sec 5.2 y 5.3)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Semilla aleatoria fija para garantizar reproducibilidad exacta",
    )
    parser.add_argument(
        "--transportadora",
        type=str,
        default="1",
        help="Identificador de la transportadora (1 a 3)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./data/type_c",
        help="Ruta del directorio de salida",
    )
    parser.add_argument(
        "--rows",
        type=int,
        default=100,
        help="Cantidad base de filas/eventos a generar",
    )
    parser.add_argument(
        "--error-rate",
        type=float,
        default=0.1,
        help="Tasa configurable de inyección de anomalías (0.0 a 1.0)",
    )
    parser.add_argument(
        "--format",
        type=str,
        default=None,
        choices=["csv", "xlsx", None],
        help="Formato de salida (por defecto toma el formato nativo de la transportadora)",
    )

    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    try:
        config = get_carrier_config(args.transportadora)
    except ValueError as e:
        print(f"Error de configuración: {e}", file=sys.stderr)
        return 1

    simulator = TypeCSimulator(
        carrier=config,
        seed=args.seed,
        error_rate=args.error_rate,
    )

    output_dir = Path(args.output_dir)
    generated_file = simulator.generate_file(
        output_dir=output_dir,
        num_rows=args.rows,
        file_format=args.format,
    )

    sha256_hash = compute_file_sha256(generated_file)

    print("=================================================================")
    print("SIMULADOR TIPO C - GENERACIÓN COMPLETADA CON ÉXITO")
    print("=================================================================")
    print(f" Transportadora : [{config.carrier_id}] {config.name} ({config.code})")
    print(f" Semilla (Seed) : {args.seed}")
    print(f" Filas base     : {args.rows}")
    print(f" Tasa de error  : {args.error_rate * 100:.1f}%")
    print(f" Archivo destino: {generated_file.resolve()}")
    print(f" SHA-256 Hash   : {sha256_hash}")
    print("=================================================================")

    return 0


if __name__ == "__main__":
    sys.exit(main())
