import ElectronStore from 'electron-store'
import type { PipelineSnapshot } from '../shared/types'
import type { PipelineSnapshotStore } from './pipeline-manager'

const StoreConstructor = (
  ElectronStore as unknown as { default?: typeof ElectronStore }
).default ?? ElectronStore

interface RunStateStore {
  snapshot: PipelineSnapshot | null
}

export function createPipelineSnapshotStore(): PipelineSnapshotStore {
  const store = new StoreConstructor<RunStateStore>({
    name: 'pipeline-state',
    defaults: { snapshot: null }
  })
  return {
    load: () => store.get('snapshot'),
    save: (snapshot) => store.set('snapshot', snapshot)
  }
}
