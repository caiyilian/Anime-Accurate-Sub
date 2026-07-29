import {
  SUBTITLE_STYLES,
  TRANSLATION_BACKENDS,
  type FilePickerKind,
  type PipelineSettings
} from '../../shared/types'

interface PipelineConfigProps {
  settings: PipelineSettings
  onChange: (settings: PipelineSettings) => void
  onPickDirectory: (field: 'projectRoot' | 'outputRoot' | 'japaneseSubtitleDir') => void
  onPickFile: (
    field: 'pythonPath' | 'translationConfigPath' | 'memoryPath' | 'glossaryPath' | 'translationMemoryPath' | 'speakerMapPath',
    kind: FilePickerKind
  ) => void
}

const styleLabels: Record<PipelineSettings['subtitleStyle'], string> = {
  anime: 'Anime 单语',
  anime_bilingual: 'Anime 双语',
  classic: 'Classic',
  karaoke: 'Karaoke'
}

function Toggle({ label, detail, checked, onChange }: { label: string; detail: string; checked: boolean; onChange: (value: boolean) => void }): React.JSX.Element {
  return (
    <label className="flex cursor-pointer gap-3 rounded-xl border border-white/8 bg-slate-950/45 p-3">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="mt-1 size-4 accent-cyan-400" />
      <span>
        <span className="block text-sm font-medium text-slate-200">{label}</span>
        <span className="mt-1 block text-xs leading-5 text-slate-500">{detail}</span>
      </span>
    </label>
  )
}

function PathInput({ label, value, placeholder, onChange, onPick }: { label: string; value: string; placeholder: string; onChange: (value: string) => void; onPick: () => void }): React.JSX.Element {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-slate-400">{label}</span>
      <span className="flex gap-2">
        <input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="min-w-0 flex-1 rounded-xl border border-white/10 bg-slate-950 px-3 py-2 font-mono text-xs outline-none focus:border-cyan-400/50" />
        <button type="button" onClick={onPick} className="rounded-xl border border-white/10 px-3 text-xs hover:bg-white/5">浏览</button>
      </span>
    </label>
  )
}

export default function PipelineConfig({ settings, onChange, onPickDirectory, onPickFile }: PipelineConfigProps): React.JSX.Element {
  const update = <K extends keyof PipelineSettings>(field: K, value: PipelineSettings[K]): void =>
    onChange({ ...settings, [field]: value })

  return (
    <section className="rounded-3xl border border-white/10 bg-white/[0.035] p-6">
      <p className="text-xs font-medium uppercase tracking-[0.18em] text-indigo-300">02 / 管线配置</p>
      <h2 className="mt-2 text-xl font-semibold">质量优先预设</h2>

      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <label className="text-xs text-slate-400">翻译后端
          <select value={settings.backend} onChange={(event) => update('backend', event.target.value as PipelineSettings['backend'])} className="mt-1.5 w-full rounded-xl border border-white/10 bg-slate-950 px-3 py-2.5 text-sm text-slate-200">
            {TRANSLATION_BACKENDS.map((backend) => <option key={backend} value={backend}>{backend}</option>)}
          </select>
        </label>
        <label className="text-xs text-slate-400">ASR
          <select value={settings.asrBackend} disabled className="mt-1.5 w-full rounded-xl border border-white/10 bg-slate-950 px-3 py-2.5 text-sm text-slate-200 disabled:opacity-70"><option>anime_whisper</option></select>
        </label>
        <label className="text-xs text-slate-400">ASS 样式
          <select value={settings.subtitleStyle} onChange={(event) => update('subtitleStyle', event.target.value as PipelineSettings['subtitleStyle'])} className="mt-1.5 w-full rounded-xl border border-white/10 bg-slate-950 px-3 py-2.5 text-sm text-slate-200">
            {SUBTITLE_STYLES.map((style) => <option key={style} value={style}>{styleLabels[style]}</option>)}
          </select>
        </label>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        <Toggle label="质量检查" detail="字幕生成后执行自动质量规则。" checked={settings.qualityCheck} onChange={(value) => update('qualityCheck', value)} />
        <Toggle label="五 Agent 审查" detail="多角色审查与保守编辑，使用 SenseNova 配置。" checked={settings.multiAgentReview} onChange={(value) => update('multiAgentReview', value)} />
        <Toggle label="GEMBA-MQM" detail="双裁判评分、验证与精修。" checked={settings.mqmQualityReview} onChange={(value) => update('mqmQualityReview', value)} />
        <Toggle label="优先日文字幕" detail="侧挂/内嵌日文字幕优先，缺失时回退 ASR。" checked={settings.preferJapaneseSubtitles} onChange={(value) => update('preferJapaneseSubtitles', value)} />
        <Toggle label="硬件自动配置" detail="让 Python 根据 GPU 与显存调整后端参数。" checked={settings.autoHardware} onChange={(value) => update('autoHardware', value)} />
        <Toggle label="OP/ED best-effort" detail="主题识别失败时继续主流程。" checked={settings.opedBestEffort} onChange={(value) => update('opedBestEffort', value)} />
        <Toggle label="单集失败后继续" detail="某一集失败时保存错误并继续后续视频；最终队列标记为失败。" checked={settings.continueOnError} onChange={(value) => update('continueOnError', value)} />
      </div>

      <details className="mt-5 rounded-2xl border border-white/10 bg-slate-950/35 p-4" open>
        <summary className="cursor-pointer text-sm font-medium text-slate-200">翻译与系列上下文</summary>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <PathInput label="翻译配置 JSON" value={settings.translationConfigPath} placeholder="可留空使用 config 默认值" onChange={(value) => update('translationConfigPath', value)} onPick={() => onPickFile('translationConfigPath', 'json')} />
          <PathInput label="系列记忆 JSON" value={settings.memoryPath} placeholder="人物、称谓、剧情记忆" onChange={(value) => update('memoryPath', value)} onPick={() => onPickFile('memoryPath', 'json')} />
          <PathInput label="术语表 JSON" value={settings.glossaryPath} placeholder="日中固定译名" onChange={(value) => update('glossaryPath', value)} onPick={() => onPickFile('glossaryPath', 'json')} />
          <PathInput label="共享翻译记忆 JSONL" value={settings.translationMemoryPath} placeholder="跨集复用已确认翻译" onChange={(value) => update('translationMemoryPath', value)} onPick={() => onPickFile('translationMemoryPath', 'json')} />
          <label className="text-xs text-slate-400">翻译批量大小（0=后端默认）
            <input type="number" min={0} max={100} value={settings.translationBatchSize} onChange={(event) => update('translationBatchSize', Number(event.target.value))} className="mt-1.5 w-full rounded-xl border border-white/10 bg-slate-950 px-3 py-2 text-sm" />
          </label>
          <label className="text-xs text-slate-400">上下文窗口（已确认前文行数）
            <input type="number" min={0} max={50} value={settings.translationContextWindow} onChange={(event) => update('translationContextWindow', Number(event.target.value))} className="mt-1.5 w-full rounded-xl border border-white/10 bg-slate-950 px-3 py-2 text-sm" />
          </label>
          <label className="text-xs text-slate-400 sm:col-span-2">AnimeThemes 系列名
            <input value={settings.opedSeries} onChange={(event) => update('opedSeries', event.target.value)} placeholder="例如 K-ON!" className="mt-1.5 w-full rounded-xl border border-white/10 bg-slate-950 px-3 py-2 text-sm" />
          </label>
        </div>
      </details>

      <details className="mt-3 rounded-2xl border border-white/10 bg-slate-950/35 p-4">
        <summary className="cursor-pointer text-sm font-medium text-slate-200">字幕、角色与运行路径</summary>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <PathInput label="日文字幕目录" value={settings.japaneseSubtitleDir} placeholder="按集数唯一匹配" onChange={(value) => update('japaneseSubtitleDir', value)} onPick={() => onPickDirectory('japaneseSubtitleDir')} />
          <PathInput label="角色映射 JSON" value={settings.speakerMapPath} placeholder="说话人名称与颜色" onChange={(value) => update('speakerMapPath', value)} onPick={() => onPickFile('speakerMapPath', 'json')} />
          <PathInput label="项目根目录" value={settings.projectRoot} placeholder="自动发现" onChange={(value) => update('projectRoot', value)} onPick={() => onPickDirectory('projectRoot')} />
          <PathInput label="Python" value={settings.pythonPath} placeholder="自动发现 .venv / Miniconda / PATH" onChange={(value) => update('pythonPath', value)} onPick={() => onPickFile('pythonPath', 'python')} />
          <div className="sm:col-span-2"><PathInput label="输出目录" value={settings.outputRoot} placeholder="项目/output/desktop" onChange={(value) => update('outputRoot', value)} onPick={() => onPickDirectory('outputRoot')} /></div>
        </div>
      </details>
    </section>
  )
}
