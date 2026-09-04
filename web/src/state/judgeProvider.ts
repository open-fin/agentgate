import { reactive, toRefs } from 'vue'

export type JudgeService = 'deepseek'|'openai'|'custom'

// Keep credentials in the SPA's in-memory session so repeated runs and page
// navigation do not require re-entry. Deliberately avoid local/session storage:
// closing or reloading the tab clears the secret.
const state = reactive({
  judgeService: 'deepseek' as JudgeService,
  judgeModel: 'deepseek-v4-pro',
  judgeApiKey: '',
  judgeBaseUrl: '',
})

export function useJudgeProviderState() {
  return toRefs(state)
}
