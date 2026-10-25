import { test, expect } from '@playwright/test';

for (const mode of ['base', 'workflow', 'cloudshrimp']) {
  test(`external ${mode} selects exact release pair and sends local token`, async ({ page }) => {
    const name = `贷款智能体 · ${mode}`;
    const targets = ['v1', 'evolution-v1', 'evolution-v2'].map((version, index) => ({
      adapter_type: 'local_bank', mode,
      descriptor: { ref: { source_id: 'local-bank-runtime', target_type: 'agent',
        external_target_id: `loan-${mode}`, external_version_id: version },
        display_name: name, content_sha256: String(index + 1).repeat(64), prompt: 'test',
        skills: [], tools: [], metadata: { version_label: version } },
    }));
    await page.route('**/web/agent/agents?*', route => route.fulfill({ json: { records: [], total: 0, current: 1, size: 1000, pages: 0 } }));
    await page.route('**/api/local-targets', route => route.fulfill({ json: { targets, unavailable: [] } }));
    await page.route('**/api/bank-targets', route => route.fulfill({ json: [] }));
    let sent = 0;
    await page.route('**/api/bank-comparisons', async route => {
      const body = route.request().postDataJSON();
      expect(route.request().headers().authorization).toBe('Bearer local');
      expect(body).toMatchObject({ mode, baseline_version: 'evolution-v1', candidate_version: 'evolution-v2',
        baseline_descriptor_sha256: '2'.repeat(64), candidate_descriptor_sha256: '3'.repeat(64),
        dataset_id: `loan-ab-${mode}`, dataset_version: 1 });
      expect(body.evaluator_refs.length).toBeGreaterThan(0);
      sent++;
      await route.fulfill({ status: 422, json: { detail: '提交契约已验证；浏览器测试不运行模型' } });
    });
    await page.goto('/#/welcome');
    await page.getByRole('button', { name: '行外Login', exact: true }).click();
    await expect(page.getByRole('heading', { name: '欢迎页面' })).toBeHidden();
    await page.goto('/#/tasks');
    await page.getByRole('button', { name: '新建测评任务', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: '新建测评任务' });
    await dialog.getByLabel('任务名称', { exact: true }).fill('版本演进浏览器验证');
    const catalogsLoaded = page.waitForResponse(response => response.url().endsWith('/api/bank-targets'));
    await dialog.getByRole('button', { name: 'A/B试验', exact: true }).click();
    await catalogsLoaded;
    await expect(dialog.locator('fieldset')).toBeEnabled();
    await dialog.locator('.target-field').filter({ has: page.getByText('选择智能体', { exact: true }) }).locator('.el-select__wrapper').click();
    await page.getByRole('option', { name, exact: true }).click();
    await dialog.locator('.target-field').filter({ has: page.getByText('实验 A · 基线版本', { exact: true }) }).locator('.el-select__wrapper').click();
    await page.getByRole('option', { name: 'evolution-v1 · evolution-v1', exact: true }).click();
    await dialog.getByLabel('平台候选版本').selectOption('evolution-v2');
    await dialog.getByLabel('任务测评集', { exact: true }).selectOption(`loan-ab-${mode}`);
    await dialog.getByRole('button', { name: '推荐评估器', exact: true }).click();
    await dialog.getByRole('button', { name: '创建 A/B试验', exact: true }).click();
    await expect.poll(() => sent).toBe(1);
    await expect(dialog.getByRole('alert')).toContainText('提交契约已验证');
  });
}
