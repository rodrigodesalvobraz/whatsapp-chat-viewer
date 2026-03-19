"""Take a screenshot of output.html showing an image with its description."""
from pathlib import Path
from playwright.sync_api import sync_playwright

current_dir = Path.cwd()
html_path = (current_dir / "output.html").resolve()
out_path = current_dir / "screenshot.png"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 524, "height": 600})
    page.goto(html_path.as_uri())
    page.wait_for_load_state("networkidle")

    # Scroll to the second image (Alice's image with description) so it's visible
    page.evaluate("""
        const messages = document.querySelectorAll('.message');
        for (const msg of messages) {
            if (msg.querySelector('img') && msg.querySelector('.transcription')) {
                msg.scrollIntoView({ block: 'center' });
                break;
            }
        }
    """)

    page.screenshot(path=str(out_path), clip={"x": 0, "y": 0, "width": 524, "height": 600})
    browser.close()

print(f"Screenshot saved: {out_path}")
