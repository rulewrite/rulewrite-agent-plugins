import { expect, test } from 'claude-code/testing'
import type { TestBody } from 'claude-code/testing'

const PLUGIN = 'pinned-todos'
const TOOL = 'mcp__pinned-todos__pin_todos'

const BAND = {
  plugin: PLUGIN,
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 12,
    bodyColumns: 80,
    scroll: { offset: 0, bodyRows: 12 },
    view: {},
  },
} as const

const TODOS = [
  { text: '브랜치 이름은?', kind: 'decision' },
  { text: '마켓플레이스 항목 수정', kind: 'task' },
]

async function start($: Parameters<TestBody>[0], on: Parameters<TestBody>[1]) {
  on('tool.register', () => ({ value: { tool: TOOL } }))
  on('command.register', () => ({ value: { command: 'todo-clear' } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)

    return <Text>engine</Text>
  })

  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
}

test('set keeps well-formed items in order, check/uncheck toggle, clear empties, list reads back', async ($, on) => {
  await start($, on)

  const set = await $.tool.call({
    tool: TOOL,
    action: 'set',
    items: [TODOS[0], { text: '   ', kind: 'task' }, { text: '종류 없음' }, TODOS[1]],
  })
  expect(set.result).toBe('pinned 2 item(s), 0 checked\n☐ 1. [결정] 브랜치 이름은?\n☐ 2. [작업] 마켓플레이스 항목 수정')

  const checked = await $.tool.call({ tool: TOOL, action: 'check', indexes: [2] })
  expect(checked.result).toBe('pinned 2 item(s), 1 checked\n☐ 1. [결정] 브랜치 이름은?\n☑ 2. [작업] 마켓플레이스 항목 수정')

  const listed = await $.tool.call({ tool: TOOL, action: 'list' })
  expect(listed.result).toBe(checked.result)

  const unchecked = await $.tool.call({ tool: TOOL, action: 'uncheck', indexes: [2] })
  expect(unchecked.result).toBe(set.result)

  const cleared = await $.tool.call({ tool: TOOL, action: 'clear' })
  expect(cleared.result).toBe('pinned 0 item(s), 0 checked')
})

test('an unknown action, a set without items and a check with no valid index are refused and leave the list as it was', async ($, on) => {
  await start($, on)
  const before = await $.tool.call({ tool: TOOL, action: 'set', items: TODOS })

  const unknown = await $.tool.call({ tool: TOOL, action: 'drop' })
  expect(unknown.deny).toMatch(/unknown action/)

  const setWithoutItems = await $.tool.call({ tool: TOOL, action: 'set' })
  expect(setWithoutItems.deny).toMatch(/needs `items`/)

  const outOfRange = await $.tool.call({ tool: TOOL, action: 'check', indexes: [0, 3, 1.5] })
  expect(outOfRange.deny).toMatch(/between 1 and 2/)

  const after = await $.tool.call({ tool: TOOL, action: 'list' })
  expect(after.result).toBe(before.result)
})

test('check keeps the valid indexes of a mixed list and counts a duplicate once', async ($, on) => {
  await start($, on)
  await $.tool.call({ tool: TOOL, action: 'set', items: TODOS })

  const checked = await $.tool.call({ tool: TOOL, action: 'check', indexes: [2, 2, 9] })
  expect(checked.result).toMatch(/^pinned 2 item\(s\), 1 checked/)
})

test('a value an earlier version stored is read as an empty list', async ($, on) => {
  on('state.get', () => ({ value: { value: [{ text: '옛 항목' }], version: 1 } }))
  await start($, on)

  const listed = await $.tool.call({ tool: TOOL, action: 'list' })
  expect(listed.result).toBe('pinned 0 item(s), 0 checked')
})

test('/todo-clear empties the list and says so', async ($, on) => {
  await start($, on)
  await $.tool.call({ tool: TOOL, action: 'set', items: TODOS })

  const ran = await $.command.run({
    command: 'todo-clear',
    args: '',
    origin: { kind: 'composer' },
    presentation: { isFullscreen: false, columns: 80 },
  })
  expect(ran.text).toBe('고정된 TODO 목록을 닫았습니다.')

  const after = await $.tool.call({ tool: TOOL, action: 'list' })
  expect(after.result).toBe('pinned 0 item(s), 0 checked')
})

test('the band draws the list, a press toggles an item, close hands the band back', async ($, on) => {
  await start($, on)

  for (const surface of ['terminal', 'desktop'] as const) {
    await $.tool.call({ tool: TOOL, action: 'set', items: TODOS })

    const ui = await $.ui.mount({ ...BAND, surface })
    expect((await ui.find({ type: 'Text', text: /TODO/ }))?.text).toBe('📌 TODO 2/2 남음')
    expect((await ui.find({ type: 'Text', text: /2\. / }))?.text).toBe('☐ 2. [작업] 마켓플레이스 항목 수정')

    await ui.press({ key: 'item-2' })
    expect((await ui.find({ type: 'Text', text: /TODO/ }))?.text).toBe('📌 TODO 1/2 남음')
    expect((await ui.find({ type: 'Text', text: /2\. / }))?.text).toBe('☑ 2. [작업] 마켓플레이스 항목 수정')

    await ui.press({ key: 'close' })
    expect((await ui.find({ type: 'Text', text: /engine/ }))?.text).toBe('engine')
    await ui.unmount()
  }
})

test('the band yields while a survey is up or the list is empty', async ($, on) => {
  await start($, on)

  const empty = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect((await empty.find({ type: 'Text' }))?.text).toBe('engine')
  await empty.unmount()

  await $.tool.call({ tool: TOOL, action: 'set', items: TODOS })
  const survey = await $.ui.mount({ ...BAND, surface: 'terminal', props: { ...BAND.props, hasSurvey: true } })
  expect((await survey.find({ type: 'Text' }))?.text).toBe('engine')
  await survey.unmount()
})
