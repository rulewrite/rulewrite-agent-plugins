import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { Todo, TodoKind } from '../types'

const TOOL = 'mcp__pinned-todos__pin_todos'

const items = atom({ plugin: 'pinned-todos', key: 'items' } as const, [], {
  shape: 'items-1',
})

const ACTIONS = ['set', 'check', 'uncheck', 'clear', 'list'] as const
type Action = (typeof ACTIONS)[number]

const KINDS: readonly TodoKind[] = ['decision', 'task']
const KIND_LABELS: Record<TodoKind, string> = { decision: '결정', task: '작업' }

function isAction(value: unknown): value is Action {
  return typeof value === 'string' && (ACTIONS as readonly string[]).includes(value)
}

function isKind(value: unknown): value is TodoKind {
  return typeof value === 'string' && (KINDS as readonly string[]).includes(value)
}

function asTodos(value: unknown): Todo[] {
  if (!Array.isArray(value)) {
    return []
  }

  const todos: Todo[] = []

  for (const one of value) {
    if (typeof one !== 'object' || one === null) {
      continue
    }

    const { text, kind } = one as Record<string, unknown>

    if (typeof text !== 'string' || text.trim().length === 0 || !isKind(kind)) {
      continue
    }

    todos.push({ text: text.trim(), kind, isDone: false })
  }

  return todos
}

function asIndexes(value: unknown, length: number): Set<number> {
  if (!Array.isArray(value)) {
    return new Set()
  }

  return new Set(
    value
      .filter((one): one is number => Number.isInteger(one) && one >= 1 && one <= length)
      .map(index => index - 1),
  )
}

function apply(list: Todo[], action: Exclude<Action, 'list'>, input: Record<string, unknown>): Todo[] | string {
  if (action === 'clear') {
    return []
  }

  if (action === 'set') {
    return Array.isArray(input.items) ? asTodos(input.items) : '`set` needs `items`; to empty the list use `clear`.'
  }

  const targets = asIndexes(input.indexes, list.length)

  if (targets.size === 0) {
    return `\`${action}\` needs \`indexes\` between 1 and ${list.length}.`
  }

  return list.map((item, index) => (targets.has(index) ? { ...item, isDone: action === 'check' } : item))
}

function line(item: Todo, index: number): string {
  return `${item.isDone ? '☑' : '☐'} ${index + 1}. [${KIND_LABELS[item.kind]}] ${item.text}`
}

function describe(list: Todo[]): string {
  const doneCount = list.filter(item => item.isDone).length

  return [`pinned ${list.length} item(s), ${doneCount} checked`, ...list.map(line)].join('\n')
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.tool.register({
      name: 'pin_todos',
      isDeferred: false,
      description: [
        'Pins what outlives the current turn above the prompt as a checklist, so the user sees what is still open after the chat scrolls: decisions the user has yet to make, and work you will do in a later turn.',
        '',
        'Rules:',
        '- Before ending a turn that leaves anything open, call `set` with the full list: one short line per item, in the user\'s language, in the order your reply presents them. `kind` is `decision` for something the user must answer or choose, `task` for work you will do later.',
        '- `set` replaces the whole list and unchecks every item: carry over the items from earlier turns that are still open, and leave out the ones already done.',
        '- Pin only what outlives the turn. Steps you take inside one turn are not items. Skip it when nothing stays open, or when the only open item is a single question your reply already asks.',
        '- When the user answers a decision, call `check` with its number (1-based). When you finish a task, `check` it. `uncheck` reopens one.',
        '- Call `clear` only when the user asks to drop the list. Never clear because every item is checked: closing the list is the user\'s choice.',
        '- When the user asks what is left, or after the context was compacted, call `list` and answer from it rather than from memory.',
        '- Not for the options of an AskUserQuestion dialog.',
      ].join('\n'),
      inputSchema: {
        type: 'object',
        properties: {
          action: { type: 'string', enum: [...ACTIONS] },
          items: {
            type: 'array',
            description: 'For `set`: the whole list, in order.',
            items: {
              type: 'object',
              properties: {
                text: { type: 'string' },
                kind: { type: 'string', enum: [...KINDS] },
              },
              required: ['text', 'kind'],
            },
          },
          indexes: {
            type: 'array',
            items: { type: 'integer', minimum: 1 },
            description: 'For `check`/`uncheck`: 1-based item numbers.',
          },
        },
        required: ['action'],
      },
    })
    await $.command.register({
      name: 'todo-clear',
      description: '입력창 위에 고정된 TODO 목록을 닫습니다',
    })

    return next(e)
  })

  on('tool.call', { tool: TOOL }, async ($, e) => {
    const { action } = e

    if (!isAction(action)) {
      return { deny: `pin_todos: unknown action ${JSON.stringify(action)}; use one of ${ACTIONS.join(', ')}.` }
    }

    if (action === 'list') {
      return { result: describe(await read($, items)) }
    }

    let refusal: string | undefined
    const list = await update($, items, current => {
      const applied = apply(current, action, e)

      if (typeof applied === 'string') {
        refusal = applied

        return current
      }

      return applied
    })

    if (refusal !== undefined) {
      return { deny: `pin_todos: ${refusal}` }
    }

    return { result: describe(list) }
  }).catch(() => ({ deny: 'pin_todos: the call failed inside the plugin; the list is unchanged.' }))

  on('command.run', { command: 'todo-clear' }, async $ => {
    await update($, items, () => [])

    return { text: '고정된 TODO 목록을 닫았습니다.' }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const list = await read($, items)

    if (e.props.hasSurvey || list.length === 0) {
      return next(e)
    }

    const { Box, Button, Text } = $.ui.resolve(e)
    const openCount = list.filter(item => !item.isDone).length

    return (
      <Box flexDirection="column" borderStyle="round" borderColor="warning" paddingX={1}>
        <Box gap={1}>
          <Text weight="bold">
            📌 TODO {openCount}/{list.length} 남음
          </Text>
          <Button key="close" hotkey="0" label="닫기" onPress={() => update($, items, () => [])} />
          <Text dimColor>(빈 프롬프트에서 0 · /todo-clear)</Text>
        </Box>
        {list.map((item, index) => (
          <Button
            key={`item-${index + 1}`}
            plain
            dimColor={item.isDone}
            onPress={() =>
              update($, items, current =>
                current.map((one, at) => (at === index ? { ...one, isDone: !one.isDone } : one)),
              )
            }
          >
            {item.isDone ? (
              <Text color="success" strikethrough>
                {line(item, index)}
              </Text>
            ) : (
              <Text>{line(item, index)}</Text>
            )}
          </Button>
        ))}
      </Box>
    )
  })
}
