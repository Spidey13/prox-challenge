"""CLI entry point for the PDF ingestion pipeline.

Usage
-----
# Ingest all PDFs for the default product (reads pdf_directory from products.json)
python run_ingest.py

# Ingest a specific product
python run_ingest.py trane_precedent

# Re-ingest from scratch (clears ChromaDB collection + rendered assets)
python run_ingest.py trane_precedent --fresh

# List all registered products and their PDF counts
python run_ingest.py --list

PowerShell note: use 'python run_ingest.py' (not 'rm -rf'; use --fresh instead).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def cmd_list(registry: dict) -> None:
    """Print all registered products and their PDF inventories."""
    if not registry:
        print("No products registered. Add entries to products.json.")
        return

    print(f"\n{'='*55}")
    print("  Registered Products")
    print(f"{'='*55}")
    for pid, product in sorted(registry.items()):
        pdfs = product.get_pdf_paths()
        pdf_dir = Path(product.pdf_directory)
        print(f"\n  {pid}")
        print(f"    Name:       {product.name}")
        print(f"    PDF dir:    {pdf_dir.resolve()}")
        if pdfs:
            for p in pdfs:
                print(f"      • {p.name}")
        else:
            print(f"      (no PDFs found in {product.pdf_directory})")
    print(f"\n{'='*55}\n")


def cmd_ingest(product_id: str, fresh: bool) -> None:
    """Discover and ingest all PDFs for the given product."""
    from ingest import ingest_product
    try:
        ingest_product(product_id, fresh=fresh)
    except FileNotFoundError as exc:
        print(f"\nERROR: {exc}")
        print("Add PDF files to the product's pdf_directory and retry.")
        sys.exit(1)
    except KeyError as exc:
        print(f"\nERROR: {exc}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest product PDFs into ChromaDB for the support agent.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "product_id",
        nargs="?",
        help="Product ID to ingest (default: value of DEFAULT_PRODUCT_ID env var).",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Clear existing ChromaDB collection and assets before ingesting.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_products",
        help="List all registered products and their PDF files, then exit.",
    )

    args = parser.parse_args()

    # Import here so config/env are loaded before we do anything
    from config import _registry, config

    if args.list_products:
        cmd_list(_registry)
        return

    product_id = args.product_id or config.default_product_id
    print(f"\nIngesting product: {product_id!r}  (--fresh={args.fresh})\n")
    cmd_ingest(product_id, fresh=args.fresh)


if __name__ == "__main__":
    main()
