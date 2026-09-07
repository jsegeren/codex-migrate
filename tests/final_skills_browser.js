// Fixed synthetic-account acceptance. No URL, token, raw browser error, trace,
// authentication card, or workspace contents are written to the result.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require('/Users/Shared/CodexMigrate-Authentic-20260906/browser-test-runtime/node_modules/playwright');
let stage = 'preflight';

async function main() {
  assert.equal(process.argv[2], '--apply');
  assert.equal(process.env.USER, 'codexmigratesource');
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  assert.match(input.token, /^[a-f0-9]{64}$/);
  assert(Number.isInteger(input.port) && input.port > 0 && input.port < 65536);
  assert.equal(input.workspace, '/Users/codexmigratesource/Codex-Migrate-BrowserSkills-20260907');
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.setDefaultTimeout(45000);
    stage = 'load-existing-pairing';
    await page.goto(`http://127.0.0.1:${input.port}/#token=${input.token}`);
    await page.locator('#paired-status').waitFor({ state: 'visible' });
    await page.locator('body').ariaSnapshot(); // Inspect fresh semantic state before interaction.
    assert((await page.locator('#paired-status').innerText()).includes('codexmigratetarget'));
    await page.getByRole('button', { name: 'Continue', exact: true }).focus();
    await page.keyboard.press('Enter');
    stage = 'select-workspace-skills';
    await page.getByRole('heading', { name: 'What would you like to move?' }).waitFor();
    await page.locator('body').ariaSnapshot();
    await page.getByLabel('What do you want to move?', { exact: true }).selectOption('skills');
    await page.getByRole('checkbox', { name: /^Personal custom skills/ }).uncheck();
    await page.getByRole('checkbox', { name: /^Workspace skills inside/ }).check();
    await page.getByText('Review or edit folder paths', { exact: true }).click();
    await page.getByLabel('Project folders to search for workspace skills, one per line').fill(input.workspace);
    await page.getByRole('button', { name: 'Review migration', exact: true }).click();
    await page.getByRole('heading', { name: 'Ready to check both Macs' }).waitFor();
    await page.locator('body').ariaSnapshot();
    assert.equal(await page.locator('#apply').isChecked(), false);
    await page.getByRole('checkbox', { name: /^Allow this migration/ }).check();
    await page.getByRole('button', { name: 'Continue to migration', exact: true }).click();
    await page.waitForURL(url => url.pathname === '/migration');
    stage = 'inspect';
    await page.locator('body').ariaSnapshot();
    await page.getByRole('button', { name: 'Inspect', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#status').textContent === 'ready');
    assert.match(await page.locator('#skill-count').innerText(), /^1 selected/);
    assert.match(await page.locator('.lede').innerText(), /selected custom skills/);
    stage = 'stage';
    await page.locator('body').ariaSnapshot();
    await page.getByRole('button', { name: 'Start transfer', exact: true }).focus();
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.querySelector('#status').textContent === 'ready to finalize', null, { timeout: 180000 });
    stage = 'confirm-finalize';
    await page.locator('body').ariaSnapshot();
    let confirmed = false;
    page.once('dialog', async dialog => {
      try {
        assert.equal(dialog.type(), 'confirm');
        assert.match(dialog.message(), /replace 1 listed skill/);
        assert.match(dialog.message(), /Conversations, configuration and whole repositories will not be migrated/);
        confirmed = true;
        await dialog.accept();
      } catch {
        await dialog.dismiss();
      }
    });
    await page.getByRole('button', { name: 'Finalize', exact: true }).focus();
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.querySelector('#status').textContent === 'complete', null, { timeout: 180000 });
    assert(confirmed);
    assert.match(await page.locator('#backup-location').innerText(), /Last verified backup/);
    assert.match(await page.locator('#skill-count').innerText(), /1 selected.*1 verified/);
    stage = 'rendered-checks';
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.locator('body').ariaSnapshot();
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    }
    // Only the synthetic skills page is captured, after its URL fragment is removed.
    assert(!new URL(page.url()).hash);
    await page.screenshot({ path: '/Users/Shared/CodexMigrate-Authentic-Status-20260906/skills-browser-320.png', fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.screenshot({ path: '/Users/Shared/CodexMigrate-Authentic-Status-20260906/skills-browser-desktop.png', fullPage: true });
    return { passed: true, browser: 'Chrome headless', existing_pairing_restored: true,
      selected_one_workspace_skill: true, changes_initially_disabled: true,
      explicit_finalize_confirmed: true, keyboard_actions_verified: true,
      backup_and_skill_verification_displayed: true, reflow_widths: [1440, 390, 320],
      native_voiceover_tested: false };
  } finally {
    await browser.close();
  }
}
main().then(result => console.log(JSON.stringify(result))).catch(() => {
  console.log(JSON.stringify({ passed: false, stage }));
  process.exitCode = 1;
});
