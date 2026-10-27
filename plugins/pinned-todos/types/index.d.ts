export type TodoKind = 'decision' | 'task'
export type Todo = { text: string; kind: TodoKind; isDone: boolean }

declare module 'claude-code' {
  interface PluginState {
    'pinned-todos': { items: Shaped<Todo[]> }
  }
}
