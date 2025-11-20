"""
Batch Runner - Process all URLs from Excel, generate configs and run tests
"""
import pandas as pd
import subprocess
import os
import re
import sys
from urllib.parse import urlparse

# Set encoding for Windows console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

EXCEL_FILE = 'Lista Verificación formularios URLs Aplicativos.xlsx'

def generate_slug_from_url(url):
    """Generate a clean slug from URL for file naming"""
    parsed = urlparse(url)
    # Get path without trailing slash
    path = parsed.path.strip('/')
    # Replace slashes with underscores, remove special chars
    slug = path.replace('/', '_').replace('-', '_')
    # Clean up multiple underscores
    slug = re.sub(r'_+', '_', slug)
    # Limit length
    if len(slug) > 50:
        slug = slug[:50]
    return slug or 'home'

def process_url(country_code, url, scan_only=False):
    """
    Process a single URL:
    1. Generate YAML if it doesn't exist (using scanner.py)
    2. Run form automation (using prueba.py) unless scan_only=True
    """
    slug = generate_slug_from_url(url)
    config_file = f'configs/{country_code}_{slug}.yaml'
    log_file = f'logs/{country_code}_{slug}_log.txt'
    
    print(f"\n{'='*80}")
    print(f"[País: {country_code}]")
    print(f"[URL: {url}]")
    print(f"[Config: {config_file}]")
    print(f"[Log: {log_file}]")
    print(f"{'='*80}")
    
    # Step 1: Scan and generate YAML if not exists
    if not os.path.exists(config_file):
        print(f">> Escaneando formulario (no existe config)...")
        try:
            result = subprocess.run(
                [sys.executable, 'scanner.py', url, config_file],
                capture_output=True,
                text=True,
                timeout=60
            )
            if result.returncode != 0:
                print(f"[ERROR] Error al escanear: {result.stderr}")
                return False
            print(f"[OK] Config generado exitosamente")
        except Exception as e:
            print(f"[ERROR] Excepción al escanear: {e}")
            return False
    else:
        print(f"[INFO] Config ya existe, usando existente")
    
    # Step 2: Run form automation
    if not scan_only:
        print(f">> Ejecutando automatización del formulario...")
        try:
            print("entre al try en batch_runner")
            result = subprocess.run(
                [sys.executable, 'prueba.py', config_file, log_file],
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode != 0:
                print("entre al if y result.returncode != 0")
                print(f"[WARN] Advertencia al ejecutar: {result.stderr}")
            print(f"[OK] Log generado: {log_file}")
            return True
        except Exception as e:
            print(f"[ERROR] Excepción al ejecutar: {e}")
            return False
    else:
        print(f"[INFO] Modo scan_only, omitiendo ejecución")
        return True

def process_sheet(sheet_name, df, scan_only=False, limit=None):
    """Process all URLs in a sheet"""
    print(f"\n\n{'#'*80}")
    print(f"# Procesando hoja: {sheet_name}")
    print(f"{'#'*80}")
    
    # Get country code (first 2-3 letters)
    country_code = sheet_name[:2].upper()
    
    # Get the column with URLs (should be first column based on our analysis)
    url_column = df.columns[0]
    urls = df[url_column].dropna().tolist()
    
    # Only keep actual URLs
    urls = [u for u in urls if isinstance(u, str) and u.startswith('http')]
    
    if limit:
        urls = urls[:limit]
    
    print(f"[INFO] Total URLs a procesar: {len(urls)}")
    
    success_count = 0
    for idx, url in enumerate(urls, 1):
        print(f"\n--- [{idx}/{len(urls)}] ---")
        if process_url(country_code, url, scan_only=scan_only):
            success_count += 1
    
    print(f"\n[SUMMARY] Completados exitosamente: {success_count}/{len(urls)}")
    return success_count, len(urls)

def main():
    # Parse arguments
    scan_only = '--scan-only' in sys.argv
    test_mode = '--test' in sys.argv
    
    if '--help' in sys.argv or '-h' in sys.argv:
        print("""
Batch Runner - Automatización masiva de formularios

Uso:
    python batch_runner.py [opciones] [hoja]

Opciones:
    --scan-only     Solo escanear y generar YAMLs, no ejecutar formularios
    --test          Modo prueba: solo procesa 2 URLs por hoja
    --help, -h      Mostrar esta ayuda

Ejemplos:
    python batch_runner.py                    # Procesa todas las hojas
    python batch_runner.py Colombia           # Procesa solo Colombia
    python batch_runner.py --test             # Prueba con 2 URLs por hoja
    python batch_runner.py --scan-only        # Solo genera configs
        """)
        return
    
    # Get sheet name if provided
    target_sheet = None
    for arg in sys.argv[1:]:
        if not arg.startswith('--'):
            target_sheet = arg
            break
    
    # Read Excel
    print(f"[INFO] Leyendo Excel: {EXCEL_FILE}")
    excel_file = pd.ExcelFile(EXCEL_FILE)
    
    # Skip 'Resumen' sheet
    sheets_to_process = [s for s in excel_file.sheet_names if s != 'Resumen']
    
    if target_sheet:
        if target_sheet in sheets_to_process:
            sheets_to_process = [target_sheet]
        else:
            print(f"[ERROR] Hoja '{target_sheet}' no encontrada")
            print(f"Hojas disponibles: {sheets_to_process}")
            return
    
    print(f"[INFO] Hojas a procesar: {sheets_to_process}")
    
    # Process each sheet
    total_success = 0
    total_urls = 0
    
    for sheet_name in sheets_to_process:
        df = pd.read_excel(excel_file, sheet_name=sheet_name)
        limit = 2 if test_mode else None
        success, total = process_sheet(sheet_name, df, scan_only=scan_only, limit=limit)
        total_success += success
        total_urls += total
    
    # Final summary
    print(f"\n\n{'='*80}")
    print(f"[FINAL] RESUMEN")
    print(f"{'='*80}")
    print(f"Total URLs procesados: {total_urls}")
    print(f"Exitosos: {total_success}")
    print(f"Fallidos: {total_urls - total_success}")
    if total_urls > 0:
        print(f"Tasa de éxito: {(total_success/total_urls*100):.1f}%")
    print(f"{'='*80}\n")

if __name__ == '__main__':
    main()
