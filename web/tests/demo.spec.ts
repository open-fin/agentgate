import { expect, test } from '@playwright/test'

test('configures an evaluation and reports real persisted metrics and evidence', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '评估配置' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '结果报告' })).toBeVisible()
  await expect(page.getByText('Evaluators & Metrics')).toBeVisible()
  await expect(page.getByLabel('Judge API Key')).toHaveAttribute('type', 'password')
  await page.getByLabel('Judge API Key').evaluate((element) => {
    const clipboard = new DataTransfer()
    clipboard.setData('text/plain', 'sk-pasted-in-browser')
    element.dispatchEvent(new ClipboardEvent('paste', {
      bubbles: true, cancelable: true, clipboardData: clipboard,
    }))
  })
  await expect(page.getByLabel('Judge API Key')).toHaveValue('sk-pasted-in-browser')
  await expect(page.locator('.case-select-list .el-checkbox')).toHaveCount(5)
  for (const name of ['低风险申请应直接批准并如实告知', '标准还款计划生成', '标准投诉受理', '标准征信查询']) {
    await page.locator('.case-select-list .el-checkbox').filter({ hasText: name }).click()
  }

  await page.getByTestId('agent-select').click()
  await page.getByRole('option', { name: /风险版本/ }).click()
  // Keep this browser smoke test offline. The request-scoped real-provider
  // path is covered by the API integration test.
  await page.locator('.el-checkbox').filter({ hasText: '回答质量' }).click()
  await page.getByRole('button', { name: /运行评估/ }).click()

  await expect(page.getByText('发布门槛未通过')).toBeVisible()
  await expect(page.getByTestId('metric-dimension-tool_use')).toContainText('工具准确率')
  await expect(page.getByTestId('metric-dimension-tool_use')).toContainText('25%')
  await page.getByRole('button', { name: /查看失败轨迹/ }).first().click()
  await expect(page.getByText('失败用例轨迹')).toBeVisible()
  await expect(page.getByText('approve_loan', { exact: true })).toBeVisible()
})

test('adds evaluator prerequisites and keeps the API key while navigating this page', async ({ page }) => {
  await page.goto('/')
  const answerQuality = page.locator('.evaluator-list .el-checkbox').filter({ hasText: '回答质量' })
  const policyCompliance = page.locator('.evaluator-list .el-checkbox').filter({ hasText: '策略合规' })

  await answerQuality.click()
  for (const evaluator of await page.locator('.evaluator-list .el-checkbox').all()) {
    if (await evaluator.evaluate(element => element.classList.contains('is-checked'))) await evaluator.click()
  }
  await answerQuality.click()

  await expect(answerQuality).toHaveClass(/is-checked/)
  await expect(policyCompliance).toHaveClass(/is-checked/)
  await expect(page.getByText('已自动选择前置评估器：策略合规')).toBeVisible()

  await page.getByLabel('Judge API Key').fill('sk-kept-in-page-memory')
  await page.getByTestId('nav-datasets').click()
  await expect(page.getByLabel('Dataset Judge API Key')).toHaveValue('sk-kept-in-page-memory')
  await page.getByTestId('nav-evaluate').click()
  await expect(page.getByLabel('Judge API Key')).toHaveValue('sk-kept-in-page-memory')
})
