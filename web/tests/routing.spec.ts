import { expect, test } from '@playwright/test'

test('uses router-backed deep links for each implemented workspace', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '评估配置' })).toBeVisible()

  await page.goto('/runs')
  await expect(page).toHaveURL(/\/runs$/)
  await expect(page.getByRole('heading', { name: '运行队列' }).last()).toBeVisible()

  await page.goto('/datasets')
  await expect(page).toHaveURL(/\/datasets$/)
  await expect(page.getByRole('heading', { name: '测评集与用例管理' })).toBeVisible()
})
