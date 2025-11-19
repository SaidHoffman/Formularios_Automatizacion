import yaml
import asyncio
import sys
import os
from playwright.async_api import async_playwright
from datetime import datetime

# Parse command-line arguments
if len(sys.argv) >= 2:
    YAML_FILE = sys.argv[1]
else:
    YAML_FILE = 'datosCO.yaml'

if len(sys.argv) >= 3:
    LOG_FILE = sys.argv[2]
else:
    base_name = os.path.splitext(os.path.basename(YAML_FILE))[0]
    LOG_FILE = f'logs/{base_name}_log.txt'

# Función para manejar modales de cookies
async def close_cookies(page):
    """Intenta cerrar el modal de cookies si está presente."""
    await page.wait_for_timeout(600)
    if await page.locator("#themaCookieModal").count():
        if await page.locator('#themaCookieModal a.btn.btnPrimario').first.is_visible():
            await page.locator('#themaCookieModal a.btn.btnPrimario').first.click()
            print("INFO: Modal de cookies cerrado mediante 'Permitir'.")
            return
        if await page.locator('#themaCookieModal button.fancybox-close-small').first.is_visible():
            await page.locator('#themaCookieModal button.fancybox-close-small').first.click()
            print("INFO: Modal de cookies cerrado mediante 'X'.")
            return
        await page.evaluate("""
            const m = document.querySelector('#themaCookieModal');
            if (m) m.remove();
        """)
        print("INFO: Modal de cookies eliminado del DOM.")

def load_data(file_path):
    """Carga la URL y los campos desde el archivo YAML."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"El archivo '{file_path}' no se encontró.")
    with open(file_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return data

async def fill_form(page, fields, log_entries):
    """Itera sobre los campos y realiza la acción de llenado correspondiente, luego envía el formulario y captura la respuesta."""
    log_entries.append("\n--- ESTADO DEL LLENADO DE CAMPOS ---")
    for i, field in enumerate(fields):
        tipo = field.get('tipo')
        selector = field.get('selector')
        valor = field.get('valor')
        log_entry = f"[{i+1}] Tipo: {tipo} | Selector: '{selector}' | Valor: '{valor}' | Estado: "
        try:
            if tipo == 'select':
                try:
                    await page.wait_for_selector(selector, state='visible', timeout=15000)
                except Exception as wait_err:
                    log_entry += f"WARN (Select no visible: {wait_err})"
                try:
                    await page.select_option(selector, label=valor, timeout=5000)
                    log_entry += "OK (Seleccionado por label)"
                except Exception:
                    try:
                        await page.select_option(selector, value=valor, timeout=5000)
                        log_entry += "OK (Seleccionado por value)"
                    except Exception as e_sel:
                        log_entry += f"ERROR (Select falló: {e_sel})"
            elif tipo == 'input_char':
                await page.fill(f'input[name="{selector}"]', valor, timeout=3000)
                log_entry += "OK (Llenado)"
            elif tipo == 'check':
                await page.set_checked(f'input[name="{selector}"]', checked=bool(valor), timeout=3000)
                log_entry += f"OK (Marcado: {valor})"
            elif tipo == 'boton':
                log_entry += "OK (Identificado para envío)"
            else:
                log_entry += "ADVERTENCIA (Tipo desconocido)"
            await page.wait_for_timeout(200)
        except Exception as e:
            log_entry += f"ERROR (Falla al interactuar: {e})"
        log_entries.append(log_entry)

    log_entries.append("--- FIN DEL LLENADO DE CAMPOS ---")
    log_entries.append("\n--- RESULTADO DEL ENVÍO ---")

    captured_status = None
    captured_id = None
    possible_keys = ['id', 'requestId', 'solicitudId', 'numeroSolicitud', 'orderId']
    boton_field = next((f for f in fields if f.get('tipo') == 'boton'), None)
    if not boton_field:
        log_entries.append("[WARN] No se encontró botón de envío en la configuración.")
    else:
        boton_selector = boton_field.get('selector')
        try:
            async with page.expect_response(lambda r: r.request.method in ["POST", "PUT"] and r.request.resource_type in ["xhr", "fetch"]) as resp_info:
                await page.click(boton_selector, timeout=5000)
            resp = resp_info.value
            captured_status = resp.status
            log_entries.append(f"[STATUS] ESTATUS HTTP CAPTURADO: {captured_status}")
            try:
                body = await resp.json()
                if isinstance(body, dict):
                    for key in possible_keys:
                        if key in body:
                            captured_id = body[key]
                            log_entries.append(f"[ID] ID ENCONTRADO EN API ({key}): {captured_id}")
                            break
                    if not captured_id:
                        log_entries.append(f"[INFO] JSON recibido sin ID claro: {body}")
                else:
                    log_entries.append("[INFO] Respuesta JSON no es un dict.")
            except Exception:
                log_entries.append("[INFO] Respuesta sin cuerpo JSON legible.")
        except Exception as e:
            log_entries.append(f"[ERROR] Error al hacer click o capturar respuesta: {e}")

    # Análisis visual de la página si aún no hay ID
    if not captured_id:
        try:
            import re
            match = re.search(r'(?:Solicitud|Pedido|Orden)\s*[:#]?\s*(\w+)', await page.inner_text('body'), re.IGNORECASE)
            if match:
                captured_id = match.group(1)
                log_entries.append(f"[ID] ID ENCONTRADO EN PÁGINA: {captured_id}")
        except Exception:
            pass
    error_sel = '.error-message'
    success_sel = '.success-message'
    if await page.locator(error_sel).is_visible():
        err_text = await page.locator(error_sel).inner_text()
        log_entries.append(f"[ERROR] ERROR EN LA PÁGINA: {err_text.strip()}")
    elif await page.locator(success_sel).is_visible():
        suc_text = await page.locator(success_sel).inner_text()
        log_entries.append(f"[SUCCESS] ÉXITO EN LA PÁGINA: {suc_text.strip()}")
    else:
        current_url = page.url
        if "gracias" in current_url.lower() or "confirmacion" in current_url.lower():
            log_entries.append(f"✅ PÁGINA DE ÉXITO DETECTADA POR URL: {current_url}")
        else:
            log_entries.append(f"ℹ️ URL ACTUAL: {current_url}")

    if captured_id:
        log_entries.append(f"*** RESULTADO FINAL: ID={captured_id} | STATUS={captured_status if captured_status else 'N/A'} ***")
    else:
        log_entries.append(f"*** RESULTADO FINAL: ID=NO_ENCONTRADO | STATUS={captured_status if captured_status else 'N/A'} ***")
    log_entries.append("---------------------------------\n")

async def main():
    log_entries = []
    try:
        data = load_data(YAML_FILE)
        url = data['url']
        campos = data['campos']
    except FileNotFoundError as e:
        log_entries.append(f"ERROR: Archivo YAML no encontrado - {e}")
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            f.write("\n".join(log_entries))
        print(f"\n❌ Error: {e}")
        return
    except Exception as e:
        log_entries.append(f"ERROR: Falló al cargar o parsear el YAML - {e}")
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            f.write("\n".join(log_entries))
        print(f"\n❌ Error al cargar YAML: {e}")
        return

    log_entries.append("--- REGISTRO DE FORMULARIO CLARO ---")
    log_entries.append(f"URL de Prueba: {url}")
    log_entries.append(f"Hora de inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url)
            await close_cookies(page)
            await page.wait_for_selector('.c13Form', timeout=15000)
            await fill_form(page, campos, log_entries)
            await browser.close()
    except Exception as e:
        log_entries.append(f"[FATAL] ERROR FATAL DEL NAVEGADOR: {e}")

    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(log_entries))
    print(f"\n[SUCCESS] Proceso completado. El registro ha sido guardado en: {LOG_FILE}")

if __name__ == '__main__':
    asyncio.run(main())
