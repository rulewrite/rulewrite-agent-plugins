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

const PINNED = 'pinned 2 item(s), 0 checked\n☐ 1. [결정] 브랜치 이름은?\n☐ 2. [작업] 마켓플레이스 항목 수정'

async function start($: Parameters<TestBody>[0], on: Parameters<TestBody>[1]) {
  on('tool.register', () => {
    return { value: { tool: TOOL } }
  })
  on('command.register', () => {
    return { value: { command: 'todo-clear' } }
  })
  on('session.start', (_, e) => {
    return { cwd: e.cwd }
  })
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)

    return <Text>engine</Text>
  })

  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
}

test('set pins the items in order, check/uncheck toggle, clear empties, list reads back', async ($, on) => {
  await start($, on)

  const set = await $.tool.call({ tool: TOOL, action: 'set', items: TODOS })
  expect(set.result).toBe(PINNED)

  const checked = await $.tool.call({ tool: TOOL, action: 'check', indexes: [2] })
  expect(checked.result).toBe('pinned 2 item(s), 1 checked\n☐ 1. [결정] 브랜치 이름은?\n☑ 2. [작업] 마켓플레이스 항목 수정')

  const listed = await $.tool.call({ tool: TOOL, action: 'list' })
  expect(listed.result).toBe(checked.result)

  const unchecked = await $.tool.call({ tool: TOOL, action: 'uncheck', indexes: [2] })
  expect(unchecked.result).toBe(PINNED)

  const cleared = await $.tool.call({ tool: TOOL, action: 'clear' })
  expect(cleared.result).toBe('pinned 0 item(s), 0 checked')
})

test('set collapses whitespace inside a text so one item stays one row', async ($, on) => {
  await start($, on)

  const set = await $.tool.call({
    tool: TOOL,
    action: 'set',
    items: [{ text: '  브랜치 이름 정하기\n- feature/x 또는\tfix/y  ', kind: 'decision' }],
  })
  expect(set.result).toBe('pinned 1 item(s), 0 checked\n☐ 1. [결정] 브랜치 이름 정하기 - feature/x 또는 fix/y')
})

test('a malformed set is refused as a whole, naming the first bad item, and writes nothing', async ($, on) => {
  let writes = 0
  on('state.set', ($, e, next) => {
    writes += 1

    return next(e)
  })
  await start($, on)
  await $.tool.call({ tool: TOOL, action: 'set', items: TODOS })
  const writesBefore = writes

  const missing = await $.tool.call({ tool: TOOL, action: 'set' })
  expect(missing.deny).toMatch(/needs `items`/)

  const empty = await $.tool.call({ tool: TOOL, action: 'set', items: [] })
  expect(empty.deny).toMatch(/empty `items`.*use `clear`/)

  const badKind = await $.tool.call({ tool: TOOL, action: 'set', items: [TODOS[0], { text: 'B', kind: 'todo' }] })
  expect(badKind.deny).toMatch(/items\[2\] has kind "todo"/)

  const blank = await $.tool.call({ tool: TOOL, action: 'set', items: [{ text: ' \n ', kind: 'task' }] })
  expect(blank.deny).toMatch(/items\[1\] needs a non-empty `text`/)

  const notObject = await $.tool.call({ tool: TOOL, action: 'set', items: ['문자열'] })
  expect(notObject.deny).toMatch(/items\[1\] must be an object/)

  expect(writes).toBe(writesBefore)
  const after = await $.tool.call({ tool: TOOL, action: 'list' })
  expect(after.result).toBe(PINNED)
})

test('a check with any index out of range is refused as a whole and writes nothing', async ($, on) => {
  let writes = 0
  on('state.set', ($, e, next) => {
    writes += 1

    return next(e)
  })
  await start($, on)
  await $.tool.call({ tool: TOOL, action: 'set', items: TODOS })
  const writesBefore = writes

  const missing = await $.tool.call({ tool: TOOL, action: 'check' })
  expect(missing.deny).toMatch(/`check` needs `indexes`/)

  const mixed = await $.tool.call({ tool: TOOL, action: 'check', indexes: [2, 9] })
  expect(mixed.deny).toMatch(/got index 9; the list has items 1 to 2/)

  const fraction = await $.tool.call({ tool: TOOL, action: 'uncheck', indexes: [1.5] })
  expect(fraction.deny).toMatch(/got index 1.5/)

  expect(writes).toBe(writesBefore)
  const after = await $.tool.call({ tool: TOOL, action: 'list' })
  expect(after.result).toBe(PINNED)

  const duplicate = await $.tool.call({ tool: TOOL, action: 'check', indexes: [2, 2] })
  expect(duplicate.result).toMatch(/^pinned 2 item\(s\), 1 checked/)
})

test('an unknown action is refused', async ($, on) => {
  await start($, on)

  const unknown = await $.tool.call({ tool: TOOL, action: 'drop' })
  expect(unknown.deny).toMatch(/unknown action "drop"/)
})

test('a subagent may not change the list', async ($, on) => {
  await start($, on)
  await $.tool.call({ tool: TOOL, action: 'set', items: TODOS })

  const fromSubagent = await $.tool.call({ tool: TOOL, action: 'clear', agentId: 'a1' })
  expect(fromSubagent.deny).toMatch(/only the main conversation/)

  const after = await $.tool.call({ tool: TOOL, action: 'list' })
  expect(after.result).toBe(PINNED)
})

test('a value an earlier version stored is read as an empty list', async ($, on) => {
  on('state.get', () => {
    return { value: { value: [{ text: '옛 항목' }], version: 1 } }
  })
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
