"""
PharmaSim auto-login scraper.
Logs in, launches the benchmark simulation, then downloads all XLS reports
from Company, Market, and Consumer Survey tabs for Year0 (Start) and Year1.

IMPORTANT: NEVER clicks Advance, Replay, or Restart buttons.
"""

import glob
import os
import random
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

LOGIN_URL = "https://schools.interpretive.com/fsui3/index.php?token=0"

USER_ID = "utda53727123"
PASSWORD = "CleverGoal2"

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOAD_DIR = os.path.join(PROJECT_ROOT, "runs")

# Sections to download, organized by tab.
# Key format matches the data-dlc / menu path used by the sim.
COMPANY_SECTIONS = [
    ("company", "company/dashboard", "Dashboard"),
    ("company", "company/performance", "Performance_Summary"),
    ("company", "company/income", "Income_Statement"),
    ("company", "company/prod_contrib", "Product_Contribution"),
    ("company", "company/sales", "Sales_Report"),
    ("company", "company/promotion", "Promotion_Report"),
    ("company", "company/portfolio", "Portfolio_Graph"),
]

MARKET_SECTIONS = [
    ("market", "market/outlook", "Industry_Outlook"),
    ("market", "market/symptoms", "Symptoms_Reported"),
    ("market", "market/formulations", "Brand_Formulations"),
    ("market", "market/sales", "Manufacturer_Sales"),
    ("market", "research/operating_stats", "Operating_Statistics"),
    ("market", "research/sales_force", "Sales_Force"),
    ("market", "research/advertising", "Advertising"),
    ("market", "research/promotion", "Promotion"),
    ("market", "research/channel_sales", "Channel_Sales"),
    ("market", "research/pricing", "Pricing"),
    ("market", "research/shopping_habits", "Shopping_Habits"),
    ("market", "research/shelf_space", "Shelf_Space"),
    ("market", "research/recommendations", "Recommendations"),
]

SURVEY_SECTIONS = [
    ("survey", "research/conjoint", "Conjoint_Analysis"),
    ("survey", "survey/brands_purchased", "Brands_Purchased"),
    ("survey", "survey/intentions", "Purchase_Intentions"),
    ("survey", "survey/satisfaction", "Satisfaction"),
    ("survey", "survey/awareness", "Brand_Awareness"),
    ("survey", "survey/criteria", "Decision_Criteria"),
    ("survey", "survey/perceptions", "Brand_Perceptions"),
    ("survey", "survey/tradeoffs", "Trade_Offs"),
]

ALL_SECTIONS = COMPANY_SECTIONS + MARKET_SECTIONS + SURVEY_SECTIONS

ALL_PERIODS = [
    (0, "Year0"),  # "Start" in the UI
    (1, "Year1"),
    (2, "Year2"),
]

# Default periods to download (Year2 only available after Decision2)
PERIODS = ALL_PERIODS[:2]


def human_delay(low=0.8, high=2.5):
    """Random sleep to mimic human interaction."""
    time.sleep(random.uniform(low, high))


def slow_type(element, text):
    """Type text character by character with random delays."""
    element.clear()
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, 0.18))


def wait_for_download(download_dir, timeout=30):
    """Wait for the most recent download to finish (no .crdownload files)."""
    end_time = time.time() + timeout
    while time.time() < end_time:
        # Check for in-progress Chrome downloads
        crdownloads = glob.glob(os.path.join(download_dir, "*.crdownload"))
        tmp_files = glob.glob(os.path.join(download_dir, "*.tmp"))
        if not crdownloads and not tmp_files:
            # Give a brief moment for the file to finalize
            time.sleep(0.5)
            crdownloads = glob.glob(os.path.join(download_dir, "*.crdownload"))
            if not crdownloads:
                return True
        time.sleep(0.5)
    return False


def login_and_launch(driver, wait):
    """Log in to the schools portal and launch the benchmark simulation."""
    # Step 1: Navigate to login page
    print("Navigating to login page...")
    driver.get(LOGIN_URL)
    human_delay(1.5, 3.0)

    # Step 2: Fill in User ID
    user_field = wait.until(EC.presence_of_element_located((By.ID, "usr")))
    human_delay(0.5, 1.2)
    slow_type(user_field, USER_ID)
    human_delay(0.6, 1.5)

    # Step 3: Fill in Password
    pass_field = driver.find_element(By.ID, "pwd")
    slow_type(pass_field, PASSWORD)
    human_delay(0.8, 2.0)

    # Step 4: Click Login
    print("Clicking Login...")
    login_btn = driver.find_element(By.ID, "Login")
    login_btn.click()

    # Step 5: Wait for dashboard
    wait.until(EC.title_contains("PharmaSim"))
    print("Login successful!")
    human_delay(1.5, 3.0)

    # Step 6: Navigate to Simulation tab
    print("Navigating to Simulation tab...")
    practice_link = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//a[contains(text(), 'Practice Decisions')]")
        )
    )
    human_delay(1.0, 2.0)
    practice_link.click()

    # Step 7: Launch Benchmark Simulation
    human_delay(1.5, 3.0)
    launch_btn = wait.until(EC.element_to_be_clickable((By.ID, "sim_solo")))
    print("Launching Benchmark Simulation...")
    human_delay(1.0, 2.5)
    launch_btn.click()

    # Step 8: Switch to simulation window
    human_delay(3.0, 5.0)
    windows = driver.window_handles
    if len(windows) > 1:
        # The simulation is the last opened window
        sim_window = windows[-1]
        driver.switch_to.window(sim_window)
        print(f"Switched to simulation window: {driver.current_url}")

        # Close the schools portal tab — we no longer need it
        portal_window = windows[0]
        driver.switch_to.window(portal_window)
        driver.close()
        driver.switch_to.window(sim_window)
        print("Closed schools portal tab.")
    else:
        raise RuntimeError("Simulation window did not open")

    # Wait for the sim to fully load
    wait.until(lambda d: d.execute_script("return typeof ui !== 'undefined' && typeof ui.menu !== 'undefined'"))
    human_delay(1.0, 2.0)
    print("Simulation loaded.")


def switch_period(driver, period_index):
    """Switch to a period (0=Start/Year0, 1=Year1) using JavaScript."""
    driver.execute_script(f"""
        var links = document.querySelectorAll('a[onclick="app.periods.activate(this);"]');
        if (links[{period_index}]) {{
            links[{period_index}].click();
        }}
    """)
    human_delay(2.0, 3.5)
    # Verify the period switched
    current = driver.execute_script("return document.getElementById('cperiod').value;")
    print(f"  Period switched to: {current}")


def navigate_to_section(driver, parent_menu, section_path):
    """Navigate to a section using the sim's JavaScript menu system."""
    driver.execute_script(
        f"ui.menu.call(null, '{parent_menu}', '{section_path}', {{}});"
    )
    human_delay(1.5, 3.0)


def download_xls(driver, section_path, period_index):
    """Trigger XLS download for the current section via a hidden iframe."""
    timestamp = int(time.time() * 1000)
    url = driver.execute_script(
        f"return ui.service.url('export-com', "
        f"'c={section_path}&t=xlsx&period={period_index}&view=export&ts={timestamp}');"
    )
    # Use a hidden iframe to trigger the download — no new tabs opened
    driver.execute_script(f"""
        var iframe = document.getElementById('download_iframe');
        if (!iframe) {{
            iframe = document.createElement('iframe');
            iframe.id = 'download_iframe';
            iframe.style.display = 'none';
            document.body.appendChild(iframe);
        }}
        iframe.src = '{url}';
    """)
    human_delay(1.5, 2.5)


def cleanup_extra_tabs(driver):
    """Close all browser tabs except the current one."""
    current = driver.current_window_handle
    for handle in driver.window_handles:
        if handle != current:
            driver.switch_to.window(handle)
            driver.close()
    driver.switch_to.window(current)


def download_all_sections(driver, download_dir, periods=None):
    """Download XLS for all sections across all periods."""
    if periods is None:
        periods = PERIODS
    for period_index, period_name in periods:
        print(f"\n{'='*60}")
        print(f"Switching to {period_name} (period={period_index})")
        print(f"{'='*60}")
        switch_period(driver, period_index)

        for parent_menu, section_path, friendly_name in ALL_SECTIONS:
            print(f"\n  [{period_name}] {friendly_name} ({section_path})...")

            # Navigate to the section
            navigate_to_section(driver, parent_menu, section_path)

            # Check if this section has a non-empty data-dlc attribute
            has_download = driver.execute_script(f"""
                var panels = document.querySelectorAll('[data-dlc]');
                for (var i = 0; i < panels.length; i++) {{
                    if (panels[i].getAttribute('data-dlc') === '{section_path}') return true;
                }}
                return false;
            """)

            if not has_download:
                print(f"    -> No download available, skipping.")
                human_delay(0.5, 1.0)
                continue

            # Record files before download
            files_before = set(glob.glob(os.path.join(download_dir, "*")))

            # Trigger download
            download_xls(driver, section_path, period_index)

            # Wait for the download to complete
            if wait_for_download(download_dir):
                files_after = set(glob.glob(os.path.join(download_dir, "*")))
                new_files = files_after - files_before
                if new_files:
                    downloaded_file = new_files.pop()
                    ext = os.path.splitext(downloaded_file)[1]
                    new_name = f"{period_name}_{friendly_name}{ext}"
                    new_path = os.path.join(download_dir, new_name)

                    # Avoid overwriting if file already exists
                    if os.path.exists(new_path):
                        os.remove(new_path)
                    os.rename(downloaded_file, new_path)
                    print(f"    -> Saved: {new_name}")
                else:
                    print(f"    -> Download triggered but no new file detected.")
            else:
                print(f"    -> Download timed out!")

            human_delay(1.0, 2.5)

            # Close any stray tabs that may have opened
            if len(driver.window_handles) > 1:
                cleanup_extra_tabs(driver)

        # Clean up after each period
        if len(driver.window_handles) > 1:
            cleanup_extra_tabs(driver)


def create_driver(download_dir: str | None = None) -> webdriver.Chrome:
    """Create a Chrome driver configured for downloading to the given directory."""
    dl_dir = download_dir or DOWNLOAD_DIR
    os.makedirs(dl_dir, exist_ok=True)

    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")

    prefs = {
        "download.default_directory": dl_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "profile.default_content_setting_values.automatic_downloads": 1,
    }
    options.add_experimental_option("prefs", prefs)

    return webdriver.Chrome(options=options)


def scrape(
    download_dir: str | None = None,
    periods: list[tuple[int, str]] | None = None,
    driver: webdriver.Chrome | None = None,
) -> str:
    """Run the full scrape pipeline.

    Args:
        download_dir: Where to save downloaded files. Defaults to DOWNLOAD_DIR.
        periods: Which periods to download. Defaults to PERIODS (Year0, Year1).
        driver: Existing Chrome driver to reuse. If None, creates a new one.

    Returns:
        The download directory path.
    """
    dl_dir = download_dir or DOWNLOAD_DIR
    owns_driver = driver is None

    if owns_driver:
        driver = create_driver(dl_dir)

    wait = WebDriverWait(driver, 20)

    try:
        login_and_launch(driver, wait)
        download_all_sections(driver, dl_dir, periods=periods)

        if len(driver.window_handles) > 1:
            cleanup_extra_tabs(driver)

        print(f"\n{'='*60}")
        print("All downloads complete!")
        print(f"Files saved in: {dl_dir}")
        print(f"{'='*60}")

        for f in sorted(os.listdir(dl_dir)):
            if f.endswith(".xlsx"):
                print(f"  {f}")

    finally:
        if owns_driver:
            driver.quit()

    return dl_dir


def main():
    scrape()


if __name__ == "__main__":
    main()
