import { useState, useEffect, useCallback, useRef } from 'react'
import { fetchJSON, subscribeSSE } from './api.js'
import ForceGraph3D from 'react-force-graph-3d'
import * as THREE from 'three'

// ====================================================================
// 主应用
// ====================================================================

export default function App() {
    const [page, setPage] = useState('dashboard')
    const [projectInfo, setProjectInfo] = useState(null)
    const [refreshKey, setRefreshKey] = useState(0)
    const [connected, setConnected] = useState(false)

    const loadProjectInfo = useCallback(() => {
        fetchJSON('/api/project/info')
            .then(setProjectInfo)
            .catch(() => setProjectInfo(null))
    }, [])

    useEffect(() => { loadProjectInfo() }, [loadProjectInfo, refreshKey])

    const refreshTimerRef = useRef(null)

    // SSE 订阅
    useEffect(() => {
        const scheduleRefresh = () => {
            if (refreshTimerRef.current) return
            refreshTimerRef.current = window.setTimeout(() => {
                setRefreshKey(k => k + 1)
                refreshTimerRef.current = null
            }, 350)
        }

        const unsub = subscribeSSE(
            () => {
                scheduleRefresh()
            },
            {
                onOpen: () => setConnected(true),
                onError: () => setConnected(false),
            },
        )
        return () => {
            if (refreshTimerRef.current) {
                window.clearTimeout(refreshTimerRef.current)
                refreshTimerRef.current = null
            }
            unsub()
            setConnected(false)
        }
    }, [])

    const title = projectInfo?.project_info?.title || '未加载'

    return (
        <div className="app-layout">
            <aside className="sidebar">
                <div className="sidebar-header">
                    <h1>PIXEL WRITER HUB</h1>
                    <div className="subtitle">{title}</div>
                </div>
                <nav className="sidebar-nav">
                    {NAV_ITEMS.map(item => (
                        <button
                            key={item.id}
                            className={`nav-item ${page === item.id ? 'active' : ''}`}
                            onClick={() => setPage(item.id)}
                        >
                            <span className="icon">{item.icon}</span>
                            <span>{item.label}</span>
                        </button>
                    ))}
                </nav>
                <div className="live-indicator">
                    <span className={`live-dot ${connected ? '' : 'disconnected'}`} />
                    {connected ? '实时同步中' : '未连接'}
                </div>
            </aside>

            <main className="main-content">
                {page === 'dashboard' && <DashboardPage data={projectInfo} key={refreshKey} />}
                {page === 'entities' && <EntitiesPage key={refreshKey} />}
                {page === 'graph' && <GraphPage key={refreshKey} />}
                {page === 'chapters' && <ChaptersPage key={refreshKey} />}
                {page === 'files' && <FilesPage />}
                {page === 'reading' && <ReadingPowerPage key={refreshKey} />}
            </main>
        </div>
    )
}

const NAV_ITEMS = [
    { id: 'dashboard', icon: '📊', label: '数据总览' },
    { id: 'entities', icon: '👤', label: '设定词典' },
    { id: 'graph', icon: '🕸️', label: '关系图谱' },
    { id: 'chapters', icon: '📝', label: '章节一览' },
    { id: 'files', icon: '📁', label: '文档浏览' },
    { id: 'reading', icon: '🔥', label: '追读力' },
]

const ENTITY_TYPE_COLORS = {
    '角色': '#4f8ff7',
    '地点': '#34d399',
    '场景': '#22c55e',
    '星球': '#22d3ee',
    '神仙': '#f59e0b',
    '势力': '#8b5cf6',
    '招式': '#ef4444',
    '法宝': '#ec4899',
    '金手指': '#14b8a6',
    '物品': '#f59e0b',
}

const RELATION_VISUALS = [
    {
        label: '敌对 / 冲突',
        color: '#d7263d',
        width: 2.8,
        matches: ['敌', '仇', '杀', '追杀', '死战', '冲突', '对抗', '背叛', '威胁', '猎杀', '围攻'],
    },
    {
        label: '盟友 / 信任',
        color: '#2ec27e',
        width: 2.4,
        matches: ['盟', '友', '信任', '合作', '守护', '保护', '帮助', '支持', '结伴', '搭档', '同伴', '认可'],
    },
    {
        label: '亲缘 / 师承',
        color: '#f5a524',
        width: 2.4,
        matches: ['亲属', '血缘', '家人', '兄妹', '兄弟', '姐妹', '父子', '母子', '母女', '父女', '师徒', '恋人', '夫妻'],
    },
    {
        label: '契约 / 持有 / 从属',
        color: '#8b5cf6',
        width: 2.2,
        matches: ['契约', '持有', '拥有', '绑定', '从属', '命令', '控制', '附着', '继承', '主仆'],
    },
    {
        label: '试探 / 利用 / 博弈',
        color: '#ff8c42',
        width: 2.0,
        matches: ['利用', '试探', '怀疑', '监视', '交易', '博弈', '拉拢', '算计', '调查'],
    },
]

const DEFAULT_RELATION_VISUAL = { label: '中立 / 未分类', color: '#26a8ff', width: 1.7 }

const NODE_SIZE_LEGEND = [
    { tier: '核心', sizeClass: 'size-large', desc: '主角 / 主线核心人物' },
    { tier: '重要', sizeClass: 'size-medium-large', desc: '卷核心角色或关键实体' },
    { tier: '次要', sizeClass: 'size-medium', desc: '稳定配角或阶段性关键点' },
    { tier: '装饰', sizeClass: 'size-small', desc: '短暂出场或背景实体' },
]

function buildNodeSprite(label, radius) {
    const text = String(label || '').trim() || '未命名'
    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d')
    const diameter = Math.max(120, radius * 28)
    const fontSize = text.length <= 4 ? 54 : text.length <= 6 ? 42 : text.length <= 8 ? 34 : 28
    const paddingX = 18
    const paddingY = 12
    const font = `700 ${fontSize}px "Noto Sans SC", sans-serif`

    ctx.font = font
    const textWidth = Math.ceil(ctx.measureText(text).width)
    canvas.width = Math.max(Math.ceil(diameter * 1.5), textWidth + paddingX * 2)
    canvas.height = Math.max(Math.ceil(diameter * 0.72), fontSize + paddingY * 2)

    ctx.font = font
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.lineJoin = 'round'
    ctx.strokeStyle = 'rgba(24, 18, 10, 0.95)'
    ctx.lineWidth = 12
    ctx.fillStyle = '#fffaf0'
    ctx.shadowColor = 'rgba(24, 18, 10, 0.45)'
    ctx.shadowBlur = 14
    ctx.shadowOffsetY = 2
    ctx.strokeText(text, canvas.width / 2, canvas.height / 2 + 1)
    ctx.shadowBlur = 0
    ctx.fillText(text, canvas.width / 2, canvas.height / 2 + 1)

    const texture = new THREE.CanvasTexture(canvas)
    texture.colorSpace = THREE.SRGBColorSpace
    const material = new THREE.SpriteMaterial({
        map: texture,
        transparent: true,
        depthWrite: false,
    })
    const sprite = new THREE.Sprite(material)
    sprite.scale.set(Math.max(radius * 2.25, canvas.width * 0.026), Math.max(radius * 0.9, canvas.height * 0.026), 1)
    return sprite
}

function buildGraphNodeObject(node) {
    const radius = Math.max(4.2, Number(node?.val || 2) * 1.02)
    const group = new THREE.Group()
    const sphere = new THREE.Mesh(
        new THREE.SphereGeometry(radius, 18, 18),
        new THREE.MeshLambertMaterial({
            color: node?.color || '#5c6078',
            emissive: node?.color || '#5c6078',
            emissiveIntensity: 0.12,
            transparent: true,
            opacity: 0.96,
        }),
    )
    const shell = new THREE.Mesh(
        new THREE.SphereGeometry(radius * 1.08, 18, 18),
        new THREE.MeshBasicMaterial({
            color: node?.color || '#5c6078',
            transparent: true,
            opacity: 0.15,
            side: THREE.BackSide,
        }),
    )
    const label = buildNodeSprite(node?.name, radius)
    label.position.set(0, 0, radius + 0.25)
    group.add(sphere)
    group.add(shell)
    group.add(label)
    return group
}

function normalizeTier(tier) {
    const value = String(tier || '').trim()
    if (!value) return '装饰'
    return value
}

function computeNodeSize(entity, relationCount) {
    const tier = normalizeTier(entity?.tier)
    const tierBase = {
        '核心': 8.4,
        '重要': 6.8,
        '次要': 5.2,
        '装饰': 4.2,
        'S': 8.4,
        'A': 6.8,
        'B': 5.2,
        'C': 4.2,
    }[tier] || 4.8
    const relationBoost = Math.min(2.4, Math.max(0, relationCount - 1) * 0.22)
    const protagonistBoost = entity?.is_protagonist ? 1.1 : 0
    return Number((tierBase + relationBoost + protagonistBoost).toFixed(2))
}

function getRelationVisual(type) {
    const raw = String(type || '').trim()
    if (!raw) return DEFAULT_RELATION_VISUAL
    const matched = RELATION_VISUALS.find(item => item.matches.some(keyword => raw.includes(keyword)))
    return matched || DEFAULT_RELATION_VISUAL
}

const FULL_DATA_GROUPS = [
    { key: 'entities', title: '实体', columns: ['id', 'canonical_name', 'type', 'tier', 'first_appearance', 'last_appearance'], domain: 'core' },
    { key: 'chapters', title: '章节', columns: ['chapter', 'title', 'word_count', 'location', 'characters'], domain: 'core' },
    { key: 'scenes', title: '场景', columns: ['chapter', 'scene_index', 'location', 'time', 'summary'], domain: 'core' },
    { key: 'aliases', title: '别名', columns: ['alias', 'entity_id', 'entity_type'], domain: 'core' },
    { key: 'stateChanges', title: '状态变化', columns: ['entity_id', 'field', 'old_value', 'new_value', 'chapter'], domain: 'core' },
    { key: 'relationships', title: '关系', columns: ['from_entity', 'to_entity', 'type', 'chapter', 'description'], domain: 'network' },
    { key: 'relationshipEvents', title: '关系事件', columns: ['from_entity', 'to_entity', 'type', 'chapter', 'event_type', 'description'], domain: 'network' },
    { key: 'readingPower', title: '追读力', columns: ['chapter', 'hook_type', 'hook_strength', 'is_transition', 'override_count', 'debt_balance'], domain: 'network' },
    { key: 'overrides', title: 'Override 合约', columns: ['chapter', 'constraint_type', 'constraint_id', 'due_chapter', 'status'], domain: 'network' },
    { key: 'debts', title: '追读债务', columns: ['id', 'debt_type', 'current_amount', 'interest_rate', 'due_chapter', 'status'], domain: 'network' },
    { key: 'debtEvents', title: '债务事件', columns: ['debt_id', 'event_type', 'amount', 'chapter', 'note'], domain: 'network' },
    { key: 'reviewMetrics', title: '审查指标', columns: ['start_chapter', 'end_chapter', 'overall_score', 'severity_counts', 'created_at'], domain: 'quality' },
    { key: 'invalidFacts', title: '无效事实', columns: ['source_type', 'source_id', 'reason', 'status', 'chapter_discovered'], domain: 'quality' },
    { key: 'checklistScores', title: '写作清单评分', columns: ['chapter', 'template', 'score', 'completion_rate', 'completed_items', 'total_items'], domain: 'quality' },
    { key: 'ragQueries', title: 'RAG 查询日志', columns: ['query_type', 'query', 'results_count', 'latency_ms', 'chapter', 'created_at'], domain: 'ops' },
    { key: 'toolStats', title: '工具调用统计', columns: ['tool_name', 'success', 'retry_count', 'error_code', 'chapter', 'created_at'], domain: 'ops' },
]

const FULL_DATA_DOMAINS = [
    { id: 'overview', label: '总览' },
    { id: 'core', label: '基础档案' },
    { id: 'network', label: '关系与剧情' },
    { id: 'quality', label: '质量审查' },
    { id: 'ops', label: 'RAG 与工具' },
]

const WORKFLOW_STAGE_ORDER = ['context_agent', 'draft', 'style_adapter', 'polish', 'data_agent']
const CHECKER_ORDER = [
    'high-point-checker',
    'consistency-checker',
    'pacing-checker',
    'ooc-checker',
    'continuity-checker',
    'reader-pull-checker',
]
const CHECKER_LABELS = {
    'high-point-checker': 'High-point',
    'consistency-checker': 'Consistency',
    'pacing-checker': 'Pacing',
    'ooc-checker': 'OOC',
    'continuity-checker': 'Continuity',
    'reader-pull-checker': 'Reader-pull',
}


// ====================================================================
// 页面 1：数据总览
// ====================================================================

function DashboardPage({ data }) {
    if (!data) return <div className="loading">加载中…</div>

    const info = data.project_info || {}
    const progress = data.progress || {}
    const protagonist = data.protagonist_state || {}
    const strand = data.strand_tracker || {}
    const foreshadowing = data.plot_threads?.foreshadowing || []

    const totalWords = progress.total_words || 0
    const targetWords = info.target_words || 2000000
    const pct = targetWords > 0 ? Math.min(100, (totalWords / targetWords * 100)).toFixed(1) : 0

    const unresolvedForeshadow = foreshadowing.filter(f => {
        const s = (f.status || '').toLowerCase()
        return s !== '已回收' && s !== '已兑现' && s !== 'resolved'
    })

    // Strand 历史统计
    const history = strand.history || []
    const strandCounts = { quest: 0, fire: 0, constellation: 0 }
    history.forEach(h => {
        const key = h?.strand || h?.dominant
        if (strandCounts[key] !== undefined) strandCounts[key]++
    })
    const total = history.length || 1

    return (
        <>
            <div className="page-header">
                <h2>📊 数据总览</h2>
                <span className="card-badge badge-blue">{info.genre || '未知题材'}</span>
            </div>

            <div className="dashboard-grid">
                <div className="card stat-card">
                    <span className="stat-label">总字数</span>
                    <span className="stat-value">{formatNumber(totalWords)}</span>
                    <span className="stat-sub">目标 {formatNumber(targetWords)} 字 · {pct}%</span>
                    <div className="progress-track">
                        <div className="progress-fill" style={{ width: `${pct}%` }} />
                    </div>
                </div>

                <div className="card stat-card">
                    <span className="stat-label">当前章节</span>
                    <span className="stat-value">第 {progress.current_chapter || 0} 章</span>
                    <span className="stat-sub">目标 {info.target_chapters || '?'} 章 · 卷 {progress.current_volume || 1}</span>
                </div>

                <div className="card stat-card">
                    <span className="stat-label">主角状态</span>
                    <span className="stat-value plain">{protagonist.name || '未设定'}</span>
                    <span className="stat-sub">
                        {protagonist.power?.realm || '未知境界'}
                        {protagonist.location?.current ? ` · ${protagonist.location.current}` : ''}
                    </span>
                </div>

                <div className="card stat-card">
                    <span className="stat-label">未回收伏笔</span>
                    <span className="stat-value" style={{ color: unresolvedForeshadow.length > 10 ? 'var(--accent-red)' : 'var(--accent-amber)' }}>
                        {unresolvedForeshadow.length}
                    </span>
                    <span className="stat-sub">总计 {foreshadowing.length} 条伏笔</span>
                </div>
            </div>

            {/* Strand Weave 比例 */}
            <div className="card dashboard-section-card">
                <div className="card-header">
                    <span className="card-title">Strand Weave 节奏分布</span>
                    <span className="card-badge badge-purple">{strand.current_dominant || '?'}</span>
                </div>
                <div className="strand-bar">
                    <div className="segment strand-quest" style={{ width: `${(strandCounts.quest / total * 100).toFixed(1)}%` }} />
                    <div className="segment strand-fire" style={{ width: `${(strandCounts.fire / total * 100).toFixed(1)}%` }} />
                    <div className="segment strand-constellation" style={{ width: `${(strandCounts.constellation / total * 100).toFixed(1)}%` }} />
                </div>
                <div className="strand-legend">
                    <span>🔵 Quest {(strandCounts.quest / total * 100).toFixed(0)}%</span>
                    <span>🔴 Fire {(strandCounts.fire / total * 100).toFixed(0)}%</span>
                    <span>🟣 Constellation {(strandCounts.constellation / total * 100).toFixed(0)}%</span>
                </div>
            </div>

            <WorkflowLivePanel />

            {/* 伏笔列表 */}
            {unresolvedForeshadow.length > 0 ? (
                <div className="card dashboard-section-card">
                    <div className="card-header">
                        <span className="card-title">⚠️ 待回收伏笔 (Top 20)</span>
                    </div>
                    <div className="table-wrap">
                        <table className="data-table">
                            <thead><tr><th>内容</th><th>状态</th><th>埋设章</th></tr></thead>
                            <tbody>
                                {unresolvedForeshadow.slice(0, 20).map((f, i) => (
                                    <tr key={i}>
                                        <td className="truncate" style={{ maxWidth: 400 }}>{f.content || f.description || '—'}</td>
                                        <td><span className="card-badge badge-amber">{f.status || '未知'}</span></td>
                                        <td>{f.chapter || f.planted_chapter || '—'}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            ) : null}

            <MergedDataView />
        </>
    )
}


// ====================================================================
// 页面 2：设定词典
// ====================================================================

function EntitiesPage() {
    const [entities, setEntities] = useState([])
    const [typeFilter, setTypeFilter] = useState('')
    const [selected, setSelected] = useState(null)
    const [changes, setChanges] = useState([])

    useEffect(() => {
        fetchJSON('/api/entities').then(setEntities).catch(() => { })
    }, [])

    useEffect(() => {
        if (selected) {
            fetchJSON('/api/state-changes', { entity: selected.id, limit: 30 }).then(setChanges).catch(() => setChanges([]))
        }
    }, [selected])

    const types = [...new Set(entities.map(e => e.type))].sort()
    const filteredEntities = typeFilter ? entities.filter(e => e.type === typeFilter) : entities

    return (
        <>
            <div className="page-header">
                <h2>👤 设定词典</h2>
                <span className="card-badge badge-green">{filteredEntities.length} / {entities.length} 个实体</span>
            </div>

            <div className="filter-group">
                <button className={`filter-btn ${typeFilter === '' ? 'active' : ''}`} onClick={() => setTypeFilter('')}>全部</button>
                {types.map(t => (
                    <button key={t} className={`filter-btn ${typeFilter === t ? 'active' : ''}`} onClick={() => setTypeFilter(t)}>{t}</button>
                ))}
            </div>

            <div className="split-layout">
                <div className="split-main">
                    <div className="card">
                        <div className="table-wrap">
                            <table className="data-table">
                                <thead><tr><th>名称</th><th>类型</th><th>层级</th><th>首现</th><th>末现</th></tr></thead>
                                <tbody>
                                    {filteredEntities.map(e => (
                                        <tr
                                            key={e.id}
                                            role="button"
                                            tabIndex={0}
                                            className={`entity-row ${selected?.id === e.id ? 'selected' : ''}`}
                                            onKeyDown={evt => (evt.key === 'Enter' || evt.key === ' ') && (evt.preventDefault(), setSelected(e))}
                                            onClick={() => setSelected(e)}
                                        >
                                            <td className={e.is_protagonist ? 'entity-name protagonist' : 'entity-name'}>
                                                {e.canonical_name} {e.is_protagonist ? '⭐' : ''}
                                            </td>
                                            <td><span className="card-badge badge-blue">{e.type}</span></td>
                                            <td>{e.tier}</td>
                                            <td>{e.first_appearance || '—'}</td>
                                            <td>{e.last_appearance || '—'}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                {selected && (
                    <div className="split-side">
                        <div className="card">
                            <div className="card-header">
                                <span className="card-title">{selected.canonical_name}</span>
                                <span className="card-badge badge-purple">{selected.tier}</span>
                            </div>
                            <div className="entity-detail">
                                <p><strong>类型：</strong>{selected.type}</p>
                                <p><strong>ID：</strong><code>{selected.id}</code></p>
                                {selected.desc && <p className="entity-desc">{selected.desc}</p>}
                                {selected.current_json && (
                                    <div className="entity-current-block">
                                        <strong>当前状态：</strong>
                                        <pre className="entity-json">
                                            {formatJSON(selected.current_json)}
                                        </pre>
                                    </div>
                                )}
                            </div>
                            {changes.length > 0 ? (
                                <div className="entity-history">
                                    <div className="card-title">状态变化历史</div>
                                    <div className="table-wrap">
                                        <table className="data-table">
                                            <thead><tr><th>章</th><th>字段</th><th>变化</th></tr></thead>
                                            <tbody>
                                                {changes.map((c, i) => (
                                                    <tr key={i}>
                                                        <td>{c.chapter}</td>
                                                        <td>{c.field}</td>
                                                        <td>{c.old_value} → {c.new_value}</td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            ) : null}
                        </div>
                    </div>
                )}
            </div>
        </>
    )
}


// ====================================================================
// 页面 3：3D 宇宙关系图谱
// ====================================================================

function GraphPage() {
    const [relationships, setRelationships] = useState([])
    const [graphData, setGraphData] = useState({ nodes: [], links: [] })

    useEffect(() => {
        Promise.all([
            fetchJSON('/api/relationships', { limit: 1000 }),
            fetchJSON('/api/entities'),
        ]).then(([rels, ents]) => {
            setRelationships(rels)
            const relatedIds = new Set()
            rels.forEach(r => { relatedIds.add(r.from_entity); relatedIds.add(r.to_entity) })
            const entityMap = {}
            ents.forEach(e => { entityMap[e.id] = e })
            const degreeMap = {}
            rels.forEach(r => {
                degreeMap[r.from_entity] = (degreeMap[r.from_entity] || 0) + 1
                degreeMap[r.to_entity] = (degreeMap[r.to_entity] || 0) + 1
            })

            const nodes = [...relatedIds].map(id => ({
                id,
                name: entityMap[id]?.canonical_name || id,
                type: entityMap[id]?.type || '未分类',
                tier: normalizeTier(entityMap[id]?.tier),
                relationCount: degreeMap[id] || 0,
                val: computeNodeSize(entityMap[id], degreeMap[id] || 0),
                color: ENTITY_TYPE_COLORS[entityMap[id]?.type] || '#5c6078',
            }))
            const links = rels.map(r => ({
                source: r.from_entity,
                target: r.to_entity,
                name: r.type,
                visual: getRelationVisual(r.type),
            }))
            setGraphData({ nodes, links })
        }).catch(() => { })
    }, [])

    return (
        <>
            <div className="page-header">
                <h2>🕸️ 关系图谱</h2>
                <span className="card-badge badge-blue">{graphData.nodes.length} 个节点</span>
                <span className="card-badge badge-green">{relationships.length} 条关系</span>
            </div>
            <div className="graph-summary-grid">
                <div className="card graph-summary-card">
                    <div className="card-title">连线颜色语义</div>
                    <div className="graph-legend-row">
                        {RELATION_VISUALS.map(item => (
                            <span key={item.label} className="graph-legend-pill">
                                <span className="graph-legend-line" style={{ background: item.color }} />
                                {item.label}
                            </span>
                        ))}
                        <span className="graph-legend-pill">
                            <span className="graph-legend-line" style={{ background: DEFAULT_RELATION_VISUAL.color }} />
                            {DEFAULT_RELATION_VISUAL.label}
                        </span>
                    </div>
                </div>
                <div className="card graph-summary-card">
                    <div className="card-title">球体大小说明</div>
                    <div className="graph-legend-row">
                        {NODE_SIZE_LEGEND.map(item => (
                            <span key={item.tier} className="graph-legend-pill">
                                <span className={`graph-size-dot ${item.sizeClass}`} />
                                {item.tier}
                            </span>
                        ))}
                    </div>
                    <p className="graph-note">大小按“设定层级 + 关系密度”计算。主角会额外放大一级。</p>
                </div>
                <div className="card graph-summary-card">
                    <div className="card-title">显示规则</div>
                    <p className="graph-note">当前关系图谱只显示已建立关系边的实体；数据库里已有但尚未建立关系的实体，会在“设定词典”里显示。</p>
                </div>
            </div>
            <div className="card graph-shell">
                <ForceGraph3D
                    graphData={graphData}
                    nodeLabel={node => `${node.name}\n类型：${node.type}\n层级：${node.tier}\n关系数：${node.relationCount || 0}`}
                    nodeThreeObject={buildGraphNodeObject}
                    nodeColor="color"
                    nodeRelSize={5.6}
                    linkLabel={link => String(link.name || '')}
                    linkColor={link => link.visual?.color || DEFAULT_RELATION_VISUAL.color}
                    linkWidth={link => link.visual?.width || DEFAULT_RELATION_VISUAL.width}
                    linkDirectionalParticles={2}
                    linkDirectionalParticleWidth={1.5}
                    linkDirectionalParticleColor={link => link.visual?.color || DEFAULT_RELATION_VISUAL.color}
                    linkDirectionalParticleSpeed={() => 0.008}
                    backgroundColor="#fffaf0"
                    showNavInfo={false}
                />
            </div>
        </>
    )
}



// ====================================================================
// 页面 4：章节一览
// ====================================================================

function ChaptersPage() {
    const [chapters, setChapters] = useState([])

    useEffect(() => {
        fetchJSON('/api/chapters').then(setChapters).catch(() => { })
    }, [])

    const totalWords = chapters.reduce((s, c) => s + (c.word_count || 0), 0)

    return (
        <>
            <div className="page-header">
                <h2>📝 章节一览</h2>
                <span className="card-badge badge-green">{chapters.length} 章 · {formatNumber(totalWords)} 字</span>
            </div>
            <div className="card">
                <div className="table-wrap">
                    <table className="data-table">
                        <thead><tr><th>章节</th><th>标题</th><th>字数</th><th>地点</th><th>角色</th></tr></thead>
                        <tbody>
                            {chapters.map(c => (
                                <tr key={c.chapter}>
                                    <td className="chapter-no">第 {c.chapter} 章</td>
                                    <td>{c.title || '—'}</td>
                                    <td>{formatNumber(c.word_count || 0)}</td>
                                    <td>{c.location || '—'}</td>
                                    <td className="truncate chapter-characters">{c.characters || '—'}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
                {chapters.length === 0 ? <div className="empty-state"><div className="empty-icon">📭</div><p>暂无章节数据</p></div> : null}
            </div>
        </>
    )
}


// ====================================================================
// 页面 5：文档浏览
// ====================================================================

function FilesPage() {
    const [tree, setTree] = useState({})
    const [selectedPath, setSelectedPath] = useState(null)
    const [content, setContent] = useState('')

    useEffect(() => {
        fetchJSON('/api/files/tree').then(setTree).catch(() => { })
    }, [])

    useEffect(() => {
        if (selectedPath) {
            fetchJSON('/api/files/read', { path: selectedPath })
                .then(d => setContent(d.content))
                .catch(() => setContent('[读取失败]'))
        }
    }, [selectedPath])

    useEffect(() => {
        if (selectedPath) return
        const first = findFirstFilePath(tree)
        if (first) setSelectedPath(first)
    }, [tree, selectedPath])

    return (
        <>
            <div className="page-header">
                <h2>📁 文档浏览</h2>
            </div>
            <div className="file-layout">
                <div className="file-tree-pane">
                    {Object.entries(tree).map(([folder, items]) => (
                        <div key={folder} className="folder-block">
                            <div className="folder-title">📂 {folder}</div>
                            <ul className="file-tree">
                                <TreeNodes items={items} selected={selectedPath} onSelect={setSelectedPath} />
                            </ul>
                        </div>
                    ))}
                </div>
                <div className="file-content-pane">
                    {selectedPath ? (
                        <div>
                            <div className="selected-path">{selectedPath}</div>
                            <div className="file-preview">{content}</div>
                        </div>
                    ) : (
                        <div className="empty-state"><div className="empty-icon">📄</div><p>选择左侧文件以预览内容</p></div>
                    )}
                </div>
            </div>
        </>
    )
}


// ====================================================================
// 页面 6：追读力
// ====================================================================

function ReadingPowerPage() {
    const [data, setData] = useState([])

    useEffect(() => {
        fetchJSON('/api/reading-power', { limit: 50 }).then(setData).catch(() => { })
    }, [])

    return (
        <>
            <div className="page-header">
                <h2>🔥 追读力分析</h2>
                <span className="card-badge badge-amber">{data.length} 章数据</span>
            </div>
            <div className="card">
                <div className="table-wrap">
                    <table className="data-table">
                        <thead><tr><th>章节</th><th>钩子类型</th><th>钩子强度</th><th>过渡章</th><th>Override</th><th>债务余额</th></tr></thead>
                        <tbody>
                            {data.map(r => (
                                <tr key={r.chapter}>
                                    <td className="chapter-no">第 {r.chapter} 章</td>
                                    <td>{r.hook_type || '—'}</td>
                                    <td>
                                        <span className={`card-badge ${r.hook_strength === 'strong' ? 'badge-green' : r.hook_strength === 'weak' ? 'badge-red' : 'badge-amber'}`}>
                                            {r.hook_strength || '—'}
                                        </span>
                                    </td>
                                    <td>{r.is_transition ? '✅' : '—'}</td>
                                    <td>{r.override_count || 0}</td>
                                    <td className={r.debt_balance > 0 ? 'debt-positive' : 'debt-normal'}>{(r.debt_balance || 0).toFixed(2)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
                {data.length === 0 ? <div className="empty-state"><div className="empty-icon">🔥</div><p>暂无追读力数据</p></div> : null}
            </div>
        </>
    )
}


function findFirstFilePath(tree) {
    const roots = Object.values(tree || {})
    for (const items of roots) {
        const p = walkFirstFile(items)
        if (p) return p
    }
    return null
}

function walkFirstFile(items) {
    if (!Array.isArray(items)) return null
    for (const item of items) {
        if (item?.type === 'file' && item?.path) return item.path
        if (item?.type === 'dir' && Array.isArray(item.children)) {
            const p = walkFirstFile(item.children)
            if (p) return p
        }
    }
    return null
}


// ====================================================================
// 数据总览内嵌：全量数据视图
// ====================================================================

function WorkflowLivePanel() {
    const [data, setData] = useState(null)
    const [loading, setLoading] = useState(true)
    const [selectedStage, setSelectedStage] = useState('')
    const [selectedStream, setSelectedStream] = useState('stdout')
    const [logContent, setLogContent] = useState('')

    useEffect(() => {
        let disposed = false
        fetchJSON('/api/workflow/live', { event_limit: 60, log_lines: 28 })
            .then(payload => {
                if (disposed) return
                setData(payload)
                const availableStages = Object.keys(payload?.stage_logs || {})
                const nextStage = payload?.active_stage || availableStages[0] || ''
                setSelectedStage(prev => (prev && availableStages.includes(prev)) ? prev : nextStage)
                setLoading(false)
            })
            .catch(() => {
                if (!disposed) {
                    setData(null)
                    setLoading(false)
                }
            })
        return () => { disposed = true }
    }, [])

    useEffect(() => {
        if (!data || !selectedStage) {
            setLogContent('')
            return
        }
        let disposed = false
        fetchJSON('/api/workflow/stage-log', {
            chapter: data.chapter,
            stage: selectedStage,
            stream: selectedStream,
        })
            .then(payload => {
                if (!disposed) setLogContent(payload?.content || '')
            })
            .catch(() => {
                if (!disposed) {
                    const fallback = data?.stage_logs?.[selectedStage]?.[`${selectedStream}_excerpt`] || ''
                    setLogContent(fallback)
                }
            })
        return () => { disposed = true }
    }, [data, selectedStage, selectedStream])

    if (loading) {
        return (
            <div className="card dashboard-section-card">
                <div className="loading">加载 workflow 状态中…</div>
            </div>
        )
    }

    if (!data) return null

    const currentTask = data.current_task || {}
    const currentStep = currentTask.current_step || {}
    const stageLogs = data.stage_logs || {}
    const stages = WORKFLOW_STAGE_ORDER.filter(stage => stageLogs[stage])
    const activeStage = data.active_stage || stages[0] || ''
    const reviewInitial = data.review?.initial || {}
    const reviewFinal = data.review?.final || {}
    const selectedLog = stageLogs[selectedStage] || stageLogs[activeStage] || null
    const events = (data.recent_events || []).slice(0, 14)
    const checkerIds = CHECKER_ORDER.filter(id => {
        return reviewInitial?.checkers?.[id] || reviewFinal?.checkers?.[id]
            || (reviewInitial?.selected_checkers || []).includes(id)
            || (reviewFinal?.selected_checkers || []).includes(id)
    })

    return (
        <>
            <div className="card dashboard-section-card">
                <div className="card-header">
                    <span className="card-title">当前流程</span>
                    <span className={`card-badge ${currentTask?.status === 'running' ? 'badge-green' : 'badge-cyan'}`}>
                        {currentTask?.status || 'idle'}
                    </span>
                </div>

                <div className="workflow-summary-grid">
                    <div className="workflow-stat-tile">
                        <span className="workflow-stat-label">活动章节</span>
                        <span className="workflow-stat-value">{data.chapter ? `第 ${data.chapter} 章` : '—'}</span>
                        <span className="stat-sub">{data.artifact_dir || '暂无 artifact dir'}</span>
                    </div>
                    <div className="workflow-stat-tile">
                        <span className="workflow-stat-label">当前步骤</span>
                        <span className="workflow-stat-value plain">{currentStep?.id || '—'}</span>
                        <span className="stat-sub">{currentStep?.name || '无活动步骤'}</span>
                    </div>
                    <div className="workflow-stat-tile">
                        <span className="workflow-stat-label">进度备注</span>
                        <span className="workflow-stat-value plain small">{currentStep?.progress_note || '—'}</span>
                        <span className="stat-sub">retry {currentTask?.retry_count || 0}</span>
                    </div>
                    <div className="workflow-stat-tile">
                        <span className="workflow-stat-label">审查得分</span>
                        <span className="workflow-stat-value plain">{reviewFinal?.overall_score || reviewInitial?.overall_score || '—'}</span>
                        <span className="stat-sub">初审 {reviewInitial?.overall_score || '—'} / 复审 {reviewFinal?.overall_score || '—'}</span>
                    </div>
                </div>

                <div className="split-layout workflow-live-layout">
                    <div className="split-main">
                        <div className="card-header workflow-subheader">
                            <span className="card-title">最近事件</span>
                            <span className="card-badge badge-purple">{events.length} 条</span>
                        </div>
                        {events.length === 0 ? (
                            <div className="empty-state compact"><p>暂无 workflow 事件</p></div>
                        ) : (
                            <div className="workflow-timeline">
                                {events.map((item, idx) => (
                                    <div className="workflow-event" key={`${item.timestamp || 'ts'}-${idx}`}>
                                        <div className="workflow-event-time">{formatTs(item.timestamp)}</div>
                                        <div className="workflow-event-body">
                                            <div className="workflow-event-title">{item.title || item.source}</div>
                                            <div className="workflow-event-message">{item.message || '—'}</div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    <div className="split-side">
                        <div className="card-header workflow-subheader">
                            <span className="card-title">阶段日志</span>
                            <span className={`card-badge ${activeStage === selectedStage ? 'badge-green' : 'badge-amber'}`}>
                                {selectedLog?.label || '未选择'}
                            </span>
                        </div>
                        <div className="workflow-stage-tabs">
                            {stages.map(stage => (
                                <button
                                    key={stage}
                                    className={`filter-btn ${selectedStage === stage ? 'active' : ''}`}
                                    onClick={() => setSelectedStage(stage)}
                                >
                                    {stageLogs[stage]?.label || stage}
                                </button>
                            ))}
                        </div>
                        <div className="workflow-stream-tabs">
                            <button className={`filter-btn ${selectedStream === 'stdout' ? 'active' : ''}`} onClick={() => setSelectedStream('stdout')}>stdout</button>
                            <button className={`filter-btn ${selectedStream === 'stderr' ? 'active' : ''}`} onClick={() => setSelectedStream('stderr')}>stderr</button>
                        </div>
                        {selectedLog?.result_summary ? (
                            <div className="workflow-stage-meta">
                                {Object.entries(selectedLog.result_summary)
                                    .filter(([, value]) => value !== null && value !== undefined && value !== '' && (!(Array.isArray(value)) || value.length > 0))
                                    .slice(0, 4)
                                    .map(([key, value]) => (
                                        <span className="workflow-meta-chip" key={key}>{key}: {formatCompactValue(value)}</span>
                                    ))}
                            </div>
                        ) : null}
                        <pre className="workflow-log-pane">{logContent || '暂无日志'}</pre>
                    </div>
                </div>
            </div>

            <div className="card dashboard-section-card">
                <div className="card-header">
                    <span className="card-title">6 Checker 初审 / 复审</span>
                    <span className="card-badge badge-blue">{checkerIds.length || 0} / 6</span>
                </div>
                {checkerIds.length === 0 ? (
                    <div className="empty-state compact"><p>当前章节还没有审查快照</p></div>
                ) : (
                    <div className="table-wrap">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>Checker</th>
                                    <th>初审</th>
                                    <th>复审</th>
                                    <th>摘要</th>
                                </tr>
                            </thead>
                            <tbody>
                                {checkerIds.map(id => {
                                    const initialRow = reviewInitial?.checkers?.[id] || null
                                    const finalRow = reviewFinal?.checkers?.[id] || null
                                    return (
                                        <tr key={id}>
                                            <td className="chapter-no">{CHECKER_LABELS[id] || id}</td>
                                            <td>{renderCheckerScore(initialRow)}</td>
                                            <td>{renderCheckerScore(finalRow)}</td>
                                            <td style={{ maxWidth: 520 }}>{finalRow?.summary || initialRow?.summary || '—'}</td>
                                        </tr>
                                    )
                                })}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </>
    )
}


function MergedDataView() {
    const [loading, setLoading] = useState(true)
    const [payload, setPayload] = useState({})
    const [domain, setDomain] = useState('overview')

    useEffect(() => {
        let disposed = false

        async function loadAll() {
            setLoading(true)
            const requests = [
                ['entities', fetchJSON('/api/entities')],
                ['chapters', fetchJSON('/api/chapters')],
                ['scenes', fetchJSON('/api/scenes', { limit: 200 })],
                ['relationships', fetchJSON('/api/relationships', { limit: 300 })],
                ['relationshipEvents', fetchJSON('/api/relationship-events', { limit: 200 })],
                ['readingPower', fetchJSON('/api/reading-power', { limit: 100 })],
                ['reviewMetrics', fetchJSON('/api/review-metrics', { limit: 50 })],
                ['stateChanges', fetchJSON('/api/state-changes', { limit: 120 })],
                ['aliases', fetchJSON('/api/aliases')],
                ['overrides', fetchJSON('/api/overrides', { limit: 120 })],
                ['debts', fetchJSON('/api/debts', { limit: 120 })],
                ['debtEvents', fetchJSON('/api/debt-events', { limit: 150 })],
                ['invalidFacts', fetchJSON('/api/invalid-facts', { limit: 120 })],
                ['ragQueries', fetchJSON('/api/rag-queries', { limit: 150 })],
                ['toolStats', fetchJSON('/api/tool-stats', { limit: 200 })],
                ['checklistScores', fetchJSON('/api/checklist-scores', { limit: 120 })],
            ]

            const entries = await Promise.all(
                requests.map(async ([key, p]) => {
                    try {
                        const val = await p
                        return [key, val]
                    } catch {
                        return [key, []]
                    }
                }),
            )
            if (!disposed) {
                setPayload(Object.fromEntries(entries))
                setLoading(false)
            }
        }

        loadAll()
        return () => { disposed = true }
    }, [])

    if (loading) return <div className="loading">加载全量数据中…</div>

    const groups = domain === 'overview'
        ? FULL_DATA_GROUPS
        : FULL_DATA_GROUPS.filter(g => g.domain === domain)
    const totalRows = FULL_DATA_GROUPS.reduce((sum, g) => sum + (payload[g.key] || []).length, 0)
    const nonEmptyGroups = FULL_DATA_GROUPS.filter(g => (payload[g.key] || []).length > 0).length
    const maxChapter = FULL_DATA_GROUPS.reduce((max, g) => {
        const rows = payload[g.key] || []
        rows.slice(0, 120).forEach(r => {
            const c = extractChapter(r)
            if (c > max) max = c
        })
        return max
    }, 0)
    const domainStats = FULL_DATA_DOMAINS.filter(d => d.id !== 'overview').map(d => {
        const ds = FULL_DATA_GROUPS.filter(g => g.domain === d.id)
        const rowCount = ds.reduce((sum, g) => sum + (payload[g.key] || []).length, 0)
        const filled = ds.filter(g => (payload[g.key] || []).length > 0).length
        return { ...d, rowCount, filled, total: ds.length }
    })

    return (
        <>
            <div className="page-header section-page-header">
                <h2>🧪 全量数据视图</h2>
                <span className="card-badge badge-cyan">{FULL_DATA_GROUPS.length} 类数据源</span>
            </div>

            <div className="demo-summary-grid">
                <div className="card stat-card">
                    <span className="stat-label">总记录数</span>
                    <span className="stat-value">{formatNumber(totalRows)}</span>
                    <span className="stat-sub">当前返回的全部数据行</span>
                </div>
                <div className="card stat-card">
                    <span className="stat-label">已覆盖数据源</span>
                    <span className="stat-value plain">{nonEmptyGroups}/{FULL_DATA_GROUPS.length}</span>
                    <span className="stat-sub">有数据的表 / 总表数</span>
                </div>
                <div className="card stat-card">
                    <span className="stat-label">最新章节触达</span>
                    <span className="stat-value plain">{maxChapter > 0 ? `第 ${maxChapter} 章` : '—'}</span>
                    <span className="stat-sub">按可识别 chapter 字段估算</span>
                </div>
                <div className="card stat-card">
                    <span className="stat-label">当前视图</span>
                    <span className="stat-value plain">{FULL_DATA_DOMAINS.find(d => d.id === domain)?.label}</span>
                    <span className="stat-sub">{groups.length} 个数据分组</span>
                </div>
            </div>

            <div className="demo-domain-tabs">
                {FULL_DATA_DOMAINS.map(item => (
                    <button
                        key={item.id}
                        className={`demo-domain-tab ${domain === item.id ? 'active' : ''}`}
                        onClick={() => setDomain(item.id)}
                    >
                        {item.label}
                    </button>
                ))}
            </div>

            {domain === 'overview' ? (
                <div className="demo-domain-grid">
                    {domainStats.map(ds => (
                        <div className="card" key={ds.id}>
                            <div className="card-header">
                                <span className="card-title">{ds.label}</span>
                                <span className="card-badge badge-purple">{ds.filled}/{ds.total}</span>
                            </div>
                            <div className="domain-stat-number">{formatNumber(ds.rowCount)}</div>
                            <div className="stat-sub">该数据域总记录数</div>
                        </div>
                    ))}
                </div>
            ) : null}

            {groups.map(g => {
                const count = (payload[g.key] || []).length
                return (
                    <div className="card demo-group-card" key={g.key}>
                        <div className="card-header">
                            <span className="card-title">{g.title}</span>
                            <span className={`card-badge ${count > 0 ? 'badge-blue' : 'badge-amber'}`}>{count} 条</span>
                        </div>
                        <MiniTable
                            rows={payload[g.key] || []}
                            columns={g.columns}
                            pageSize={12}
                        />
                    </div>
                )
            })}
        </>
    )
}

function MiniTable({ rows, columns, pageSize = 12 }) {
    const [page, setPage] = useState(1)

    useEffect(() => {
        setPage(1)
    }, [rows, columns, pageSize])

    if (!rows || rows.length === 0) {
        return <div className="empty-state compact"><p>暂无数据</p></div>
    }

    const totalPages = Math.max(1, Math.ceil(rows.length / pageSize))
    const safePage = Math.min(page, totalPages)
    const start = (safePage - 1) * pageSize
    const list = rows.slice(start, start + pageSize)

    return (
        <>
            <div className="table-wrap">
                <table className="data-table">
                    <thead>
                        <tr>{columns.map(c => <th key={c}>{c}</th>)}</tr>
                    </thead>
                    <tbody>
                        {list.map((row, i) => (
                            <tr key={i}>
                                {columns.map(c => (
                                    <td key={c} className="truncate" style={{ maxWidth: 240 }}>
                                        {formatCell(row?.[c])}
                                    </td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            <div className="table-pagination">
                <button
                    className="page-btn"
                    type="button"
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={safePage <= 1}
                >
                    上一页
                </button>
                <span className="page-info">
                    第 {safePage} / {totalPages} 页 · 共 {rows.length} 条
                </span>
                <button
                    className="page-btn"
                    type="button"
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                    disabled={safePage >= totalPages}
                >
                    下一页
                </button>
            </div>
        </>
    )
}

function extractChapter(row) {
    if (!row || typeof row !== 'object') return 0
    const candidates = [
        row.chapter,
        row.start_chapter,
        row.end_chapter,
        row.chapter_discovered,
        row.first_appearance,
        row.last_appearance,
    ]
    for (const c of candidates) {
        const n = Number(c)
        if (Number.isFinite(n) && n > 0) return n
    }
    return 0
}


// ====================================================================
// 子组件：文件树递归
// ====================================================================

function TreeNodes({ items, selected, onSelect, depth = 0 }) {
    const [expanded, setExpanded] = useState({})
    if (!items || items.length === 0) return null

    return items.map((item, i) => {
        const key = item.path || `${depth}-${i}`
        if (item.type === 'dir') {
            const isOpen = expanded[key]
            return (
                <li key={key}>
                    <div
                        className="tree-item"
                        role="button"
                        tabIndex={0}
                        onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), setExpanded(prev => ({ ...prev, [key]: !prev[key] })))}
                        onClick={() => setExpanded(prev => ({ ...prev, [key]: !prev[key] }))}
                    >
                        <span className="tree-icon">{isOpen ? '📂' : '📁'}</span>
                        <span>{item.name}</span>
                    </div>
                    {isOpen && item.children && (
                        <ul className="tree-children">
                            <TreeNodes items={item.children} selected={selected} onSelect={onSelect} depth={depth + 1} />
                        </ul>
                    )}
                </li>
            )
        }
        return (
            <li key={key}>
                <div
                    className={`tree-item ${selected === item.path ? 'active' : ''}`}
                    role="button"
                    tabIndex={0}
                    onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onSelect(item.path))}
                    onClick={() => onSelect(item.path)}
                >
                    <span className="tree-icon">📄</span>
                    <span>{item.name}</span>
                </div>
            </li>
        )
    })
}


// ====================================================================
// 辅助：数字格式化
// ====================================================================

function formatNumber(n) {
    if (n >= 10000) return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 }).format(n / 10000) + ' 万'
    return new Intl.NumberFormat('zh-CN').format(n)
}

function renderCheckerScore(row) {
    if (!row) return '—'
    return `${row.score ?? '—'} / ${row.pass ? 'PASS' : 'FAIL'}`
}

function formatTs(value) {
    if (!value) return '—'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return String(value)
    return date.toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
    })
}

function formatCompactValue(value) {
    if (Array.isArray(value)) {
        return value.length <= 2 ? value.join(' / ') : `${value.slice(0, 2).join(' / ')} ...`
    }
    if (typeof value === 'object' && value !== null) {
        return formatCell(value)
    }
    return String(value)
}

function formatJSON(str) {
    try {
        return JSON.stringify(JSON.parse(str), null, 2)
    } catch {
        return str
    }
}

function formatCell(v) {
    if (v === null || v === undefined) return '—'
    if (typeof v === 'boolean') return v ? 'true' : 'false'
    if (typeof v === 'object') {
        try {
            return JSON.stringify(v)
        } catch {
            return String(v)
        }
    }
    const s = String(v)
    return s.length > 180 ? `${s.slice(0, 180)}...` : s
}
