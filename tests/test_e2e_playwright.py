"""
Deterministyczny zestaw testów E2E w Playwright dla panelu Prometeusz Web UI.
Weryfikuje pełny przepływ end-to-end, branding, metryki, interakcje chatu,
autouzupełnianie komend slash oraz zarządzanie panelem pomocniczym.
"""

import os
import re
import subprocess
import sys
import time
import urllib.request
import pytest
from playwright.sync_api import Page, sync_playwright, expect

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session")
def live_server():
    """
    Zapewnia działający serwer FastAPI z zamontowanym frontendem dist.
    Uruchamia uvicorn w tle, czeka na gotowość przez /api/metrics,
    a po zakończeniu sesji testowej bezpiecznie go zamyka.
    """
    base_url = "http://127.0.0.1:8000"
    server_started_by_fixture = False
    proc = None

    # 1. Sprawdź czy serwer już działa na porcie 8000
    try:
        with urllib.request.urlopen(f"{base_url}/api/metrics", timeout=1) as resp:
            if resp.status == 200:
                yield base_url
                return
    except Exception:
        pass

    # 2. Uruchom serwer uvicorn w procesie potomnym
    env = os.environ.copy()
    env["PYTHONPATH"] = "/workspace/prometeusz"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd="/workspace/prometeusz",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    server_started_by_fixture = True

    # 3. Aktywne oczekiwanie na gotowość serwera (max 15s)
    ready = False
    start_time = time.time()
    while time.time() - start_time < 15:
        try:
            with urllib.request.urlopen(f"{base_url}/api/metrics", timeout=1) as resp:
                if resp.status == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(0.25)

    if not ready:
        if proc:
            proc.kill()
            out, err = proc.communicate()
            raise RuntimeError(f"Serwer uvicorn nie wystartował w czasie 15s. Stdout: {out.decode()}, Stderr: {err.decode()}")
        raise RuntimeError("Brak możliwości połączenia z serwerem na porcie 8000.")

    yield base_url

    # 4. Teardown: czyste zatrzymanie serwera
    if server_started_by_fixture and proc:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


@pytest.fixture(scope="session")
def browser_instance():
    """
    Uruchamia JEDNĄ instancję Chromium dla całej sesji testowej z twardymi limitami RAM (max 256MB).
    Zapobiega wyciekom pamięci i OOM Killerowi.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-extensions",
                "--js-flags=--max-old-space-size=256",
            ],
        )
        try:
            yield browser
        finally:
            try:
                browser.close()
            except Exception:
                pass


@pytest.fixture(scope="function")
def browser_page(browser_instance, live_server: str):
    """
    Czysta, lekka strona per test, zawsze zamykana w bloku finally.
    """
    context = browser_instance.new_context(
        viewport={"width": 1440, "height": 900},
        ignore_https_errors=True,
    )
    page = context.new_page()
    try:
        page.goto(live_server, wait_until="networkidle", timeout=15000)
        yield page
    finally:
        try:
            page.close()
        except Exception:
            pass
        try:
            context.close()
        except Exception:
            pass


def test_01_server_health_and_navigation(browser_page: Page, live_server: str):
    """Scenariusz 1: Nawigacja do http://127.0.0.1:8000/ i weryfikacja załadowania aplikacji."""
    assert browser_page.url.rstrip("/") == live_server.rstrip("/")
    expect(browser_page.locator("body > #app")).to_be_visible()


def test_02_branding_and_three_column_layout(browser_page: Page):
    """Scenariusz 2: Tytuł strony, branding PROMETEUSZ oraz trójkolumnowy układ."""
    # Tytuł strony
    assert "Prometeusz" in browser_page.title()
    assert "Antigravity" in browser_page.title()

    # Branding w lewym sidebarze (używamy .first lub selektora klasy z logo)
    branding = browser_page.locator("#sidebar-left span.font-bold:has-text('PROMETEUSZ')").first
    expect(branding).to_be_visible()
    assert "PROMETEUSZ" in branding.inner_text().strip()

    sub_brand = browser_page.locator("#sidebar-left span:has-text('Antigravity 2.0')").first
    expect(sub_brand).to_be_visible()

    # Trójkolumnowy układ UI
    left_col = browser_page.locator("body > #app > #sidebar-left")
    middle_col = browser_page.locator("body > #app > main")
    right_col = browser_page.locator("body > #app > #sidebar-right")

    expect(left_col).to_be_visible()
    expect(middle_col).to_be_visible()
    expect(right_col).to_be_visible()


def test_03_server_metrics_panel(browser_page: Page):
    """Scenariusz 3: Wskaźniki metryk serwera w czasie rzeczywistym (CPU, RAM, Dysk) w popoverze docka."""
    btn_resources = browser_page.locator("#btn-server-resources")
    expect(btn_resources).to_be_visible()
    btn_resources.click()

    metrics_panel = browser_page.locator("#metrics-panel")
    expect(metrics_panel).to_be_visible()

    # CPU
    cpu_val = browser_page.locator("#cpu-value")
    cpu_bar = browser_page.locator("#cpu-bar")
    expect(cpu_val).to_be_visible()
    expect(cpu_bar).to_be_visible()
    expect(cpu_val).to_have_text(re.compile(r"\d+.*%"))

    # RAM
    ram_val = browser_page.locator("#ram-value")
    ram_bar = browser_page.locator("#ram-bar")
    expect(ram_val).to_be_visible()
    expect(ram_bar).to_be_visible()
    expect(ram_val).to_have_text(re.compile(r"GB|\d+"))

    # Dysk
    disk_val = browser_page.locator("#disk-value")
    disk_bar = browser_page.locator("#disk-bar")
    expect(disk_val).to_be_visible()
    expect(disk_bar).to_be_visible()
    expect(disk_val).to_have_text(re.compile(r"\d+.*%"))


def test_04_chat_interactions(browser_page: Page):
    """
    Scenariusz 4: Interakcje chatu:
    - zwijanie i rozwijanie bloku 'Thought for...',
    - renderowanie karty narzędziowej ze stdout,
    - wysyłanie nowej wiadomości przez pole input.
    """
    # 1. Zwijanie i rozwijanie 'Thought for...'
    thought_header = browser_page.locator(".thought-header").first
    thought_content = browser_page.locator(".thought-content").first
    expect(thought_header).to_be_visible()

    # Domyślnie zwinięty
    expect(thought_content).to_be_hidden()

    # Rozwijanie po kliknięciu
    thought_header.click()
    expect(thought_content).to_be_visible()

    # Ponowne zwijanie
    thought_header.click()
    expect(thought_content).to_be_hidden()

    # 2. Karta narzędziowa z terminalowym stdout
    tool_card = browser_page.locator(".tool-card").first
    expect(tool_card).to_be_visible()
    stdout_code = tool_card.locator(".tool-stdout-container pre code")
    expect(stdout_code).to_be_visible()
    assert len(stdout_code.inner_text().strip()) > 0

    copy_btn = tool_card.locator(".btn-copy-out")
    expect(copy_btn).to_be_visible()

    # Przechwycenie /api/chat aby uniknąć uruchamiania prawdziwego CLI i zaśmiecania bazy sesji
    def handle_chat_route(route):
        route.fulfill(
            status=200,
            headers={"Content-Type": "application/x-ndjson"},
            body='{"type": "text_delta", "delta": "Otrzymano i przekazano polecenie: Weryfikacja automatyczna Playwright E2E"}\n{"type": "done"}\n',
        )

    browser_page.route("**/api/chat", handle_chat_route)
    try:
        # 3. Wysłanie nowej wiadomości przez input
        chat_input = browser_page.locator("#chat-input")
        expect(chat_input).to_be_visible()
        test_msg = "Weryfikacja automatyczna Playwright E2E"
        chat_input.fill(test_msg)

        send_btn = browser_page.locator("#btn-send-message")
        send_btn.click()

        # Czyszczenie pola promptu
        assert chat_input.input_value() == ""

        # Pojawienie się wiadomości użytkownika w strumieniu
        user_bubble = browser_page.locator("#chat-stream p.whitespace-pre-wrap").filter(has_text=test_msg).first
        expect(user_bubble).to_be_visible(timeout=5000)

        # Odpowiedź asystenta wygenerowana po przetworzeniu
        assistant_reply = browser_page.locator("#chat-stream .assistant-turn .markdown-body").filter(has_text="Otrzymano i przekazano polecenie").last
        expect(assistant_reply).to_be_visible(timeout=5000)
    finally:
        browser_page.unroute("**/api/chat")



def test_05_slash_commands_autocomplete(browser_page: Page):
    """Scenariusz 5: Autouzupełnianie komend slash po wpisaniu '/' w prompt."""
    chat_input = browser_page.locator("#chat-input")
    slash_popup = browser_page.locator("main > #slash-autocomplete")
    slash_list = browser_page.locator("#slash-commands-list")

    # Domyślnie popup schowany
    assert "hidden" in (slash_popup.get_attribute("class") or "")

    # Wpisanie '/'
    chat_input.fill("/")
    chat_input.dispatch_event("input")

    # Popup staje się widoczny
    expect(slash_popup).to_be_visible(timeout=3000)
    assert "hidden" not in (slash_popup.get_attribute("class") or "")

    # Lista zawiera komendy (np. /goal, /plan itp.)
    commands = slash_list.locator("> div")
    expect(commands.first).to_be_visible()
    assert commands.count() >= 3

    # Wybór komendy /goal
    goal_opt = slash_list.locator("text=/goal").first
    expect(goal_opt).to_be_visible()
    goal_opt.click()

    # Popup znika, a prompt zostaje uzupełniony
    assert "hidden" in (slash_popup.get_attribute("class") or "")
    assert chat_input.input_value().strip() == "/goal"


def test_06_auxiliary_panel_tabs_and_collapse(browser_page: Page):
    """
    Scenariusz 6: Przełączanie zakładek w Auxiliary panel
    (Artifacts, Terminal z xterm, Changes) oraz zwijanie panelu pomocniczego.
    """
    right_sidebar = browser_page.locator("#sidebar-right")
    expect(right_sidebar).to_be_visible()

    # 1. Przełączenie na zakładkę Terminal
    terminal_tab_btn = browser_page.locator('#sidebar-right button[data-tab="terminal"]')
    terminal_content = browser_page.locator("#sidebar-right #tab-content-terminal")
    terminal_tab_btn.click()

    expect(terminal_content).to_be_visible()
    expect(browser_page.locator("#sidebar-right #xterm-container")).to_be_visible()
    expect(browser_page.locator("#sidebar-right #pty-status-text")).to_be_visible()

    # 2. Przełączenie na zakładkę Changes
    changes_tab_btn = browser_page.locator('#sidebar-right button[data-tab="changes"]')
    changes_content = browser_page.locator("#sidebar-right #tab-content-changes")
    changes_tab_btn.click()

    expect(changes_content).to_be_visible()
    expect(browser_page.locator("#sidebar-right #changes-list")).to_be_visible()
    expect(browser_page.locator("#sidebar-right #changes-count-badge")).to_be_visible()

    # 3. Powrót do Artifacts
    artifacts_tab_btn = browser_page.locator('#sidebar-right button[data-tab="artifacts"]')
    artifacts_content = browser_page.locator("#sidebar-right #tab-content-artifacts")
    artifacts_tab_btn.click()

    expect(artifacts_content).to_be_visible()

    # 4. Zwinięcie panelu przyciskiem 'X'
    btn_close_aux = browser_page.locator("#btn-close-auxiliary")
    btn_close_aux.click()
    expect(right_sidebar).to_be_hidden()

    # 5. Rozwinięcie panelu przyciskiem w docku
    btn_toggle_aux = browser_page.locator("#btn-toggle-auxiliary")
    btn_toggle_aux.click()
    expect(right_sidebar).to_be_visible()


def test_07_browser_resource_cleanup(live_server: str):
    """
    Scenariusz 7: Weryfikacja czystego zamknięcia przeglądarki (browser.close())
    w celu oszczędzania pamięci RAM kontenera piaskownicy.
    """
    import concurrent.futures

    def _isolated_browser_test():
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--js-flags=--max-old-space-size=128"],
            )
            try:
                assert browser.is_connected() is True
                context = browser.new_context()
                try:
                    page = context.new_page()
                    page.goto(live_server, wait_until="domcontentloaded")
                    assert "Prometeusz" in page.title()
                finally:
                    context.close()
            finally:
                browser.close()
                assert browser.is_connected() is False

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(_isolated_browser_test).result()


def test_08_horizontal_header_alignment(browser_page: Page):
    """
    Scenariusz 8: Weryfikacja usunięcia nagłówka środkowego (#chat-header)
    oraz wyrównania wysokości nagłówków paneli bocznych (lewy i prawy).
    """
    left_header = browser_page.locator("#sidebar-left-header")
    right_header = browser_page.locator("#sidebar-right-header")
    mid_header = browser_page.locator("#chat-header")

    # Środkowy nagłówek czatu jest całkowicie usunięty
    expect(mid_header).to_have_count(0)

    expect(left_header).to_be_visible()
    expect(right_header).to_be_visible()

    b_left = left_header.bounding_box()
    b_right = right_header.bounding_box()

    assert b_left is not None and b_right is not None
    # Wysokości nagłówków paneli bocznych muszą być równe
    assert round(b_left["height"]) == round(b_right["height"])
    assert round(b_left["y"]) == round(b_right["y"])


def test_09_sidebar_resizers(browser_page: Page):
    """
    Scenariusz 9: Weryfikacja przesuwania paneli bocznych za pomocą resizerów.
    """
    resizer_left = browser_page.locator("#resizer-left")
    resizer_right = browser_page.locator("#resizer-right")
    sidebar_left = browser_page.locator("#sidebar-left")
    sidebar_right = browser_page.locator("#sidebar-right")

    expect(resizer_left).to_be_visible()
    expect(resizer_right).to_be_visible()

    initial_left_width = sidebar_left.bounding_box()["width"]
    initial_right_width = sidebar_right.bounding_box()["width"]

    # Przeciągnij lewy separator o 50px w prawo
    b_rl = resizer_left.bounding_box()
    browser_page.mouse.move(b_rl["x"] + b_rl["width"] / 2, b_rl["y"] + b_rl["height"] / 2)
    browser_page.mouse.down()
    browser_page.mouse.move(b_rl["x"] + b_rl["width"] / 2 + 50, b_rl["y"] + b_rl["height"] / 2)
    browser_page.mouse.up()

    new_left_width = sidebar_left.bounding_box()["width"]
    assert new_left_width > initial_left_width

    # Przeciągnij prawy separator o 50px w lewo (zwiększ prawy panel)
    b_rr = resizer_right.bounding_box()
    browser_page.mouse.move(b_rr["x"] + b_rr["width"] / 2, b_rr["y"] + b_rr["height"] / 2)
    browser_page.mouse.down()
    browser_page.mouse.move(b_rr["x"] + b_rr["width"] / 2 - 50, b_rr["y"] + b_rr["height"] / 2)
    browser_page.mouse.up()

    new_right_width = sidebar_right.bounding_box()["width"]
    assert new_right_width > initial_right_width


def test_10_workspace_picker_from_prompt_and_removed_side_tabs(browser_page: Page):
    """
    Scenariusz 10: Weryfikacja usunięcia zakładek files i uploads z prawego panelu
    oraz poprawnego działania pickera plików workspace wywoływanego z prompta.
    """
    # 1. Sprawdź, że w prawym panelu nie ma zakładek 'files' i 'uploads'
    expect(browser_page.locator('#sidebar-right button[data-tab="files"]')).to_have_count(0)
    expect(browser_page.locator('#sidebar-right button[data-tab="uploads"]')).to_have_count(0)

    # 2. Otwórz menu '+' w prompt barze
    btn_plus = browser_page.locator("#btn-plus-attach")
    expect(btn_plus).to_be_visible()
    btn_plus.click()

    popover = browser_page.locator("#plus-popover")
    expect(popover).to_be_visible()

    # 3. Kliknij 'Przeglądaj pliki workspace'
    btn_ws = browser_page.locator("#btn-popover-workspace")
    expect(btn_ws).to_be_visible()
    btn_ws.click()

    # 4. Sprawdź, że modal się otworzył i załadował pliki (bez błędu JS)
    modal = browser_page.locator("#workspace-files-modal")
    expect(modal).to_be_visible()

    tree = browser_page.locator("#modal-workspace-tree")
    expect(tree).to_be_visible()
    # Oczekujemy, że zniknie napis ładowania lub błędu, a pojawią się elementy
    browser_page.wait_for_timeout(500)
    expect(tree).not_to_contain_text("Nie udało się załadować listy plików")

    # Powinny być widoczne elementy folderów/plików
    items = tree.locator("> div")
    assert items.count() > 0

    # 5. Zamknij modal
    btn_close = browser_page.locator("#btn-close-workspace-files")
    btn_close.click()
    expect(modal).to_be_hidden()


def test_11_navigation_dock_modals_and_fonts(browser_page: Page):
    """
    Scenariusz 11: Weryfikacja nowej architektury nawigacji:
    - Logo Prometeusza w lewym górnym rogu UI
    - Kompaktowy utility dock (CPU, Panel, Pomoc, Ustawienia)
    - Ikona ołówka do edycji nazwy sesji na karcie sesji
    - Dynamiczna zmiana --font-size-base na :root
    - Customowy ciemny modal Prometeusza
    """
    # 1. Logo w nagłówku sidebara
    logo = browser_page.locator('#sidebar-left-header img[src="/logo.png"]')
    expect(logo).to_be_visible()

    # 2. Dock z kompaktowymi ikonkami
    dock = browser_page.locator("#utility-dock")
    expect(dock).to_be_visible()
    expect(dock.locator("#btn-server-resources")).to_be_visible()
    expect(dock.locator("#btn-toggle-auxiliary")).to_be_visible()
    expect(dock.locator("#btn-shortcuts-help")).to_be_visible()
    expect(dock.locator("#btn-open-settings")).to_be_visible()

    # 3. Ikona ołówka (edycja nazwy) na karcie sesji
    rename_btn = browser_page.locator(".btn-rename-session").first
    expect(rename_btn).to_be_attached()

    # 4. Customowy prompt modal po kliknięciu ołówka
    rename_btn.click()
    prompt_modal = browser_page.locator("#custom-prompt-modal")
    expect(prompt_modal).to_be_visible()

    # Zamknięcie modala przez Anuluj
    btn_cancel = prompt_modal.locator("#btn-cancel-prompt-modal")
    btn_cancel.click()
    expect(prompt_modal).to_be_hidden()

    # 5. Dynamiczna zmiana rozmiaru czcionki w ustawieniach
    btn_settings = browser_page.locator("#utility-dock #btn-open-settings")
    btn_settings.click()

    settings_modal = browser_page.locator("#settings-modal")
    expect(settings_modal).to_be_visible()

    font_select = browser_page.locator("#setting-font-size")
    expect(font_select).to_be_visible()

    # Zmień na 16px
    font_select.select_option("16px")

    # Zweryfikuj, że na :root dynamicznie ustawiono --font-size-base = 16px
    font_size_val = browser_page.evaluate("document.documentElement.style.getPropertyValue('--font-size-base')")
    assert font_size_val.strip() == "16px"

    # Zamknij ustawienia
    btn_close_settings = browser_page.locator("#btn-close-settings")
    btn_close_settings.click()
    expect(settings_modal).to_be_hidden()


def test_12_gemini_style_attachment_and_logo(browser_page: Page):
    """
    Scenariusz 12: Weryfikacja logo bez zaokrąglenia, faviconu oraz kafelków załącznika w stylu Gemini:
    - Logo z object-contain i brakiem zaokrągleń
    - Favicon z /logo.png?v=2
    - Dodanie załącznika wyświetla kafelek nad promptem z ciemnym tłem (#2a2b3d), rounded-xl,
      plakietką rozszerzenia w uppercase, uciętą nazwą oraz krzyżykiem 'x'
    - Brak ścieżki file:/// w polu chat-input
    - Usunięcie krzyżykiem 'x' usuwa załącznik
    """
    # 1. Logo i Favicon
    logo = browser_page.locator('#sidebar-left-header img[src="/logo.png"]')
    expect(logo).to_be_visible()
    logo_classes = logo.get_attribute("class") or ""
    assert "object-contain" in logo_classes
    assert "rounded-lg" not in logo_classes
    assert "rounded-full" not in logo_classes

    favicon = browser_page.locator('link[rel="icon"][href="/logo.png?v=2"]')
    expect(favicon).to_have_count(1)

    # 2. Załączenie pliku przez API instancji PrometeuszApp
    browser_page.evaluate("""() => {
        window.app.addAttachment({
            name: "VencordInstaller.exe",
            path: "/workspace/.uploads/VencordInstaller.exe",
            size: 1048576
        });
    }""")

    # 3. Weryfikacja kafelka nad promptem
    bar = browser_page.locator("#prompt-attachments-bar")
    expect(bar).to_be_visible()

    # Rozszerzenie wielkimi literami
    ext_badge = bar.locator("span:has-text('EXE')")
    expect(ext_badge).to_be_visible()

    # Ucięta nazwa
    file_name_el = bar.locator("div.truncate:has-text('VencordInstall')")
    expect(file_name_el).to_be_visible()

    # Pole prompta nie zawiera file:///
    chat_input = browser_page.locator("#chat-input")
    assert "file://" not in chat_input.input_value()

    # 4. Usunięcie załącznika krzyżykiem 'x'
    btn_remove = bar.locator(".btn-remove-attachment")
    expect(btn_remove).to_be_visible()
    btn_remove.click()

    # Pasek powinien zostać ukryty
    expect(bar).to_be_hidden()


def test_13_conversations_management_and_prompt_clean(browser_page: Page):
    """
    Scenariusz 13: Weryfikacja usunięcia eksportu z promptu, dynamicznej listy agentów
    oraz nowej zakładki Zarządzanie rozmowami w Ustawieniach.
    """
    # 1. Usuń przycisk eksportu z paska promptu
    btn_export_pill = browser_page.locator("#btn-export-chat-pill")
    expect(btn_export_pill).to_have_count(0)

    # 2. Dynamiczny dropdown ról agentów zasilany z /api/agents
    role_select = browser_page.locator("#bottom-role-select")
    expect(role_select).to_be_visible()
    # Opcja Domyślna jest obecna
    default_opt = role_select.locator("option[value='']")
    expect(default_opt).to_have_count(1)
    # Dynamiczne opcje agentów (np. @lead-engineer lub @frontend-artisan)
    expect(role_select.locator("option[value='lead-engineer']")).to_have_count(1)
    expect(role_select.locator("option[value='frontend-artisan']")).to_have_count(1)

    # 3. Otwarcie Ustawień i nowa piąta zakładka "Zarządzanie rozmowami"
    btn_settings = browser_page.locator("#utility-dock #btn-open-settings")
    btn_settings.click()

    settings_modal = browser_page.locator("#settings-modal")
    expect(settings_modal).to_be_visible()

    tab_conv_btn = settings_modal.locator("button[data-settings-tab='conversations']")
    expect(tab_conv_btn).to_be_visible()
    expect(tab_conv_btn).to_contain_text("Zarządzanie rozmowami")

    # Przełącz na zakładkę Zarządzanie rozmowami
    tab_conv_btn.click()

    tab_conv_content = settings_modal.locator("#settings-tab-conversations")
    expect(tab_conv_content).to_be_visible()

    # Pasek narzędzi z licznikiem i odświeżaniem
    btn_reload = tab_conv_content.locator("#btn-reload-conversations-mgmt")
    expect(btn_reload).to_be_visible()
    count_badge = tab_conv_content.locator("#conversations-mgmt-count")
    expect(count_badge).to_be_visible()

    # Lista rozmów
    conv_list = tab_conv_content.locator("#conversations-mgmt-list")
    expect(conv_list).to_be_visible()

    # Jeśli są elementy na liście, przetestuj hover i widoczność przycisków Sforkuj i Eksportuj
    rows = conv_list.locator(".group")
    if rows.count() > 0:
        first_row = rows.first
        first_row.hover()
        btn_fork = first_row.locator(".btn-fork-session")
        expect(btn_fork).to_be_visible()
        expect(btn_fork).to_contain_text("Sforkuj")
        btn_export = first_row.locator(".btn-export-session")
        expect(btn_export).to_be_visible()
        expect(btn_export).to_contain_text("Eksportuj")

    # Zamknij modal
    btn_close = settings_modal.locator("#btn-close-settings")
    btn_close.click()
    expect(settings_modal).to_be_hidden()




