import yaml
import asyncio
import sys
import os
from playwright.async_api import async_playwright
from datetime import datetime
from urllib.parse import urlparse

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
        print(f"[DEBUG] Selector del botón: {boton_selector}")
        
        try:
            await page.wait_for_selector(boton_selector, state='visible', timeout=15000)
        except Exception as e:
            log_entries.append(f"[ERROR] Botón no visible: {e}")
            captured_status = None
            captured_id = None
        else:
            # Capturar URL inicial antes del envío
            initial_url = page.url
            
            # Capturar todas las respuestas durante el click
            responses_captured = []
            
            def capture_response(response):
                responses_captured.append({
                    'url': response.url,
                    'status': response.status,
                    'method': response.request.method,
                    'type': response.request.resource_type,
                    'response': response
                })
                print(f"[DEBUG] Capturada: {response.request.method} {response.url} [{response.status}] ({response.request.resource_type})")
            
            page.on("response", capture_response)
            
            try:
                # Hacer click y esperar a que se procesen las respuestas
                await page.click(boton_selector, timeout=20000)
                await page.wait_for_timeout(3000)  # Esperar 3 segundos para capturar respuestas
                
                # Verificar si hubo cambio de URL
                final_url = page.url
                url_changed = initial_url != final_url
                
                if url_changed:
                    log_entries.append(f"[SUCCESS] URL cambió después del envío")
                    log_entries.append(f"  Inicial: {initial_url}")
                    log_entries.append(f"  Final: {final_url}")
                
                # Filtrar tracking pixels y recursos estáticos
                tracking_domains = [
                    'facebook.com', 'google-analytics.com', 'doubleclick.net', 
                    'googletagmanager.com', 'analytics.google.com', 'tiktok', 
                    'hotjar.com', 'clarity.ms', 'mixpanel.com', 'segment.com',
                    'amplitude.com', 'heap.io', 'google.com/pagead', 'google.com/ads',
                    'ads.google.com', 'google.com/recaptcha'
                ]
                static_types = ['stylesheet', 'script', 'image', 'font', 'media']
                
                filtered_responses = []
                for resp_data in responses_captured:
                    # Skip tracking pixels
                    if any(domain in resp_data['url'] for domain in tracking_domains):
                        continue
                    # Skip static resources
                    if resp_data['type'] in static_types:
                        continue
                    filtered_responses.append(resp_data)
                
                # Get the form's domain for prioritization
                form_domain = urlparse(page.url).netloc
                
                # Buscar la respuesta más relevante con prioridades:
                # 1. POST/PUT del mismo dominio
                # 2. POST/PUT de cualquier dominio
                # 3. Cualquier respuesta del mismo dominio
                # 4. Cualquier otra respuesta
                relevant_response = None
                
                # Priority 1: POST/PUT from same domain
                for resp_data in filtered_responses:
                    resp_domain = urlparse(resp_data['url']).netloc
                    if resp_data['method'] in ['POST', 'PUT'] and resp_domain == form_domain:
                        relevant_response = resp_data
                        break
                
                # Priority 2: Any POST/PUT
                if not relevant_response:
                    for resp_data in filtered_responses:
                        if resp_data['method'] in ['POST', 'PUT']:
                            relevant_response = resp_data
                            break
                
                # Priority 3: Any response from same domain
                if not relevant_response:
                    for resp_data in filtered_responses:
                        resp_domain = urlparse(resp_data['url']).netloc
                        if resp_domain == form_domain:
                            relevant_response = resp_data
                            break
                
                # Priority 4: Any other response
                if not relevant_response and filtered_responses:
                    relevant_response = filtered_responses[0]
                
                if relevant_response:
                    captured_status = relevant_response['status']
                    print(f"[DEBUG] Response seleccionada: {relevant_response['method']} {relevant_response['url']} [{captured_status}]")
                    log_entries.append(f"[STATUS] ESTATUS HTTP CAPTURADO: {captured_status} ({relevant_response['method']} {relevant_response['url']})")
                    
                    try:
                        body = await relevant_response['response'].json()
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
                else:
                    log_entries.append(f"[WARN] No se capturó ninguna respuesta relevante. Total capturadas: {len(responses_captured)}, Filtradas: {len(filtered_responses)}")
                    
            except Exception as e:
                log_entries.append(f"[ERROR] Error al hacer click: {e}")
                captured_status = None
            finally:
                page.remove_listener("response", capture_response)

    # Análisis visual de la página si aún no hay ID
    if not captured_id:
        try:
            import re
            page_text = await page.inner_text('body')
            # Buscar patrones de ID en el texto de la página
            match = re.search(r'(?:Solicitud|Pedido|Orden|Request|Ticket|Folio|Número|Number)[:\s#]*([A-Z0-9\-]{6,})', page_text, re.IGNORECASE)
            if match:
                captured_id = match.group(1)
                log_entries.append(f"[ID] ID ENCONTRADO EN PÁGINA: {captured_id}")
        except Exception:
            pass
    
    # Buscar indicadores de éxito en la página
    error_sel = '.error-message, .alert-danger, [class*="error"]'
    success_sel = 'i.ico-check-circle, .alert-success, .success-message, [class*="success"]'
    
    try:
        if await page.locator(error_sel).first.is_visible():
            err_text = await page.locator(error_sel).first.inner_text()
            log_entries.append(f"[ERROR] ERROR EN LA PÁGINA: {err_text.strip()}")
        elif await page.locator(success_sel).first.is_visible():
            success_text = await page.locator(success_sel).first.inner_text()
            log_entries.append(f"[SUCCESS] ÉXITO EN LA PÁGINA: {success_text.strip()}")
        else:
            current_url = page.url
            # Buscar keywords de éxito en la URL o contenido
            success_keywords = ['gracias', 'thank', 'confirmacion', 'confirmation', 'exito', 'success', 'completado', 'complete']
            page_text_lower = (await page.inner_text('body')).lower()
            
            if any(keyword in current_url.lower() for keyword in success_keywords):
                log_entries.append(f"✅ PÁGINA DE ÉXITO DETECTADA POR URL: {current_url}")
            elif any(keyword in page_text_lower for keyword in success_keywords):
                log_entries.append(f"✅ MENSAJE DE ÉXITO DETECTADO EN CONTENIDO")
            else:
                log_entries.append(f"ℹ️ URL ACTUAL: {current_url}")
    except Exception as e:
        log_entries.append(f"[WARN] Error al verificar indicadores de éxito: {e}")

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
