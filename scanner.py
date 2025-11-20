import asyncio
import yaml
import re
from playwright.async_api import async_playwright
from urllib.parse import urlparse

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

async def scan_form(url, output_yaml_path):
    """
    Scan a URL for form fields and generate a YAML config
    """
    print(f"\n[INFO] Scanning form at: {url}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        try:
            await page.goto(url, timeout=30000)
            await close_cookies(page)
            
            # Wait for form - try specific class first, then generic
            try:
                await page.wait_for_selector('.c13Form', timeout=15000)
                form_selector = '.c13Form'
                print(f"  [INFO] Usando formulario con clase .c13Form")
            except:
                await page.wait_for_selector('form', timeout=15000)
                form_selector = 'form'
                print(f"  [INFO] Usando primer formulario encontrado")
            
            await page.wait_for_timeout(2000)  # Extra wait for JS
            
            campos = []
            
            # Work within the specific form to avoid confusion
            form = page.locator(form_selector).first
            
            # 1. Detect SELECT fields
            selects = await form.locator('select').all()
            for idx, select in enumerate(selects):
                try:
                    # Get all options
                    options = await select.locator('option').all()
                    option_texts = []
                    for opt in options:
                        text = await opt.inner_text()
                        if text.strip() and text.strip() not in ['Seleccione', 'Selecciona', '']:
                            option_texts.append(text.strip())
                    
                    if option_texts:
                        # Use first non-empty option as default
                        default_value = option_texts[0] if option_texts else ""
                        
                        # Try to get a better selector (name, id, or form-scoped nth-child)
                        name_attr = await select.get_attribute('name')
                        id_attr = await select.get_attribute('id')
                        
                        if name_attr:
                            selector = f'select[name="{name_attr}"]'
                        elif id_attr:
                            selector = f'#{id_attr}'
                        else:
                            # Use form-scoped nth-child instead of nth-of-type
                            selector = f'.c13Form select:nth-child({idx+1})'
                        
                        campos.append({
                            'tipo': 'select',
                            'selector': selector,
                            'valor': default_value,
                            'opciones': option_texts[:5]  # Store first 5 options for reference
                        })
                        print(f"  [OK] SELECT encontrado: {selector} - {option_texts[:3]}...")
                except Exception as e:
                    print(f"  [WARN] Error al procesar select {idx}: {e}")
            
            # 2. Detect INPUT fields (text, tel, email)
            inputs = await form.locator('input[type="text"], input[type="tel"], input[type="email"], input[type="number"], input:not([type])').all()
            for inp in inputs:
                try:
                    name = await inp.get_attribute('name') or ''
                    placeholder = await inp.get_attribute('placeholder') or ''
                    input_type = await inp.get_attribute('type') or 'text'
                    
                    # Skip if hidden or no name
                    if not name or not await inp.is_visible():
                        continue
                    
                    # Determine default value based on field hints
                    lower_hints = (name + ' ' + placeholder).lower()
                    if 'phone' in lower_hints or 'tel' in lower_hints or 'celular' in lower_hints:
                        default_value = '3001234567'
                    elif 'email' in lower_hints or 'correo' in lower_hints:
                        default_value = 'test@example.com'
                    elif 'name' in lower_hints or 'nombre' in lower_hints:
                        default_value = 'Said Sigala Moráles'
                    elif 'cedula' in lower_hints or 'documento' in lower_hints or 'id' in lower_hints:
                        default_value = '5578033729'
                    else:
                        default_value = 'test_value'
                    
                    campos.append({
                        'tipo': 'input_char',
                        'selector': name,
                        'valor': default_value,
                        'placeholder': placeholder
                    })
                    print(f"  [OK] INPUT encontrado: {name} ({placeholder})")
                except Exception as e:
                    print(f"  [WARN] Error al procesar input: {e}")
            
            # 3. Detect CHECKBOX fields
            checkboxes = await form.locator('input[type="checkbox"]').all()
            for cb in checkboxes:
                try:
                    name = await cb.get_attribute('name') or ''
                    if not name or not await cb.is_visible():
                        continue
                    
                    campos.append({
                        'tipo': 'check',
                        'selector': name,
                        'valor': True
                    })
                    print(f"  [OK] CHECKBOX encontrado: {name}")
                except Exception as e:
                    print(f"  [WARN] Error al procesar checkbox: {e}")
            
            # 4. Detect SUBMIT button - try multiple strategies
            btn_selector = None
            btn_text = ""
            
            # Strategy 1: Look for explicit submit buttons
            buttons = await form.locator('button[type="submit"], input[type="submit"]').all()
            if not buttons:
                # Strategy 2: Look for buttons with common submit classes
                buttons = await form.locator('button.btn, button.btnPrimario, button.submit, button[class*="submit"]').all()
            if not buttons:
                # Strategy 3: Look for buttons with submit-related text
                buttons = await form.locator('button:has-text("Enviar"), button:has-text("Solicitar"), button:has-text("Submit"), button:has-text("Continuar")').all()
            if not buttons:
                # Strategy 4: Just get any button in the form
                buttons = await form.locator('button').all()
            
            for btn in buttons:
                try:
                    if await btn.is_visible():
                        # Get button attributes
                        btn_id = await btn.get_attribute('id')
                        btn_class = await btn.get_attribute('class')
                        btn_type = await btn.get_attribute('type')
                        btn_text = (await btn.inner_text()).strip()
                        
                        # Build selector - prefer ID, then class, then type
                        if btn_id:
                            btn_selector = f'#{btn_id}'
                        elif btn_class:
                            # Use the most specific class
                            class_list = [c for c in btn_class.split() if c]
                            if class_list:
                                btn_selector = 'button.' + '.'.join(class_list[:3])  # Use first 3 classes max
                            else:
                                btn_selector = 'button[type="submit"]' if btn_type == 'submit' else 'button'
                        elif btn_type == 'submit':
                            btn_selector = 'button[type="submit"]'
                        else:
                            # Last resort: use text content
                            btn_selector = f'button:has-text("{btn_text[:20]}")'  # Limit text length
                        
                        campos.append({
                            'tipo': 'boton',
                            'selector': btn_selector,
                            'valor': '',
                            'texto': btn_text
                        })
                        print(f"  [OK] BOTÓN encontrado: {btn_selector} - '{btn_text}'")
                        break  # Only add first visible submit button
                except Exception as e:
                    print(f"  [WARN] Error al procesar botón: {e}")
            
            # If no button found, add a warning
            if not btn_selector:
                print(f"  [WARN] No se encontró botón de envío en el formulario")
            
            # Generate YAML
            yaml_data = {
                'url': url,
                'campos': campos
            }
            
            with open(output_yaml_path, 'w', encoding='utf-8') as f:
                yaml.dump(yaml_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            
            print(f"\n[OK] YAML generado: {output_yaml_path}")
            print(f"   Total campos detectados: {len(campos)}")
            
        except Exception as e:
            print(f"\n[ERROR] Error al escanear formulario: {e}")
            raise
        finally:
            await browser.close()

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("Uso: python scanner.py <URL> [output.yaml]")
        sys.exit(1)
    
    url = sys.argv[1]
    
    # Generate output filename if not provided
    if len(sys.argv) >= 3:
        output_file = sys.argv[2]
    else:
        slug = generate_slug_from_url(url)
        output_file = f"configs/{slug}.yaml"
    
    asyncio.run(scan_form(url, output_file))
