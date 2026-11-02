import sys
from pathlib import Path

from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).parent))
from test_browser_vouchers import app  # noqa: F401  (fixture)


def open_new_company(page):
    page.locator('#screen').focus()
    page.keyboard.press('Alt+k')
    expect(page.locator('#dialog-title')).to_have_text('List of Companies')
    page.locator('#dialog-body button', has_text='Create Company').click()
    expect(page.locator('#field-name')).to_be_focused()


def test_company_dates_can_be_typed_with_dashes_and_fill_the_year(app):
    page, db, _ = app
    open_new_company(page)
    start, end, books = (page.locator(f'#field-{n}') for n in ('starting_from', 'ending_at', 'books_from'))
    # A new company opens on the current 1 April - 31 March year.
    assert start.input_value().endswith('-04-01') and end.input_value().endswith('-03-31')

    page.locator('#field-name').fill('Dates Co')
    start.focus()
    page.wait_for_timeout(50)  # a person types after the field has selected its text
    start.press_sequentially('1-4-2025')   # '-' used to step the date instead of typing
    start.press('Enter')
    expect(start).to_have_value('2025-04-01')
    expect(end).to_have_value('2026-03-31')
    expect(books).to_have_value('2025-04-01')

    page.keyboard.press('Control+a')
    expect(page.locator('#status')).not_to_have_text('')
    meta = db.get_company('Dates Co')
    assert (meta['starting_from'], meta['ending_at']) == ('20250401', '20260331')


def test_calendar_keeps_typing_focus_and_escape_does_not_quit_the_form(app):
    page, _, _ = app
    open_new_company(page)
    start = page.locator('#field-starting_from')
    start.click()
    expect(page.locator('.date-picker-popup')).to_be_visible()
    expect(start).to_be_focused()
    page.keyboard.press('Escape')
    expect(page.locator('.date-picker-popup')).to_be_hidden()
    expect(page.locator('#overlay')).to_be_hidden()
    expect(page.locator('#field-name')).to_be_visible()
