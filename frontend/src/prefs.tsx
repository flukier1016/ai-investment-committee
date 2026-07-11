// 界面偏好：日间/夜间主题 + 中/英语言。
// t() 以中文串为键查词典；EN 模式缺项回退中文（引擎生成的叙事文本保持中文）。

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { dictCore } from './i18n/dict-core'
import { dictA } from './i18n/dict-a'
import { dictB } from './i18n/dict-b'

export type Theme = 'light' | 'dark'
export type Lang = 'zh' | 'en'

const THEME_KEY = 'ai_committee_theme_v1'
const LANG_KEY = 'ai_committee_lang_v1'

const dict: Record<string, string> = { ...dictCore, ...dictA, ...dictB }

// 模块级当前语言：让 t()/格式化器可以在任意位置使用；
// Provider 切换语言时更新它并触发整棵树重渲染，读取值总是最新。
let langNow: Lang = (localStorage.getItem(LANG_KEY) as Lang) ?? 'zh'

// 组合词前缀（桶/大类名），用于翻译引擎生成的观点标签，如「中国股票趋势转强」
const COMPOSITE_PREFIXES = ['中国股票', '外国股票', '中国债券', '外国债券', '商品', '外汇', '现金', '权益', '债券']

export function t(s: string): string {
  if (langNow !== 'en') return s
  const hit = dict[s]
  if (hit !== undefined) return hit
  for (const prefix of COMPOSITE_PREFIXES) {
    if (s.startsWith(prefix)) {
      const rest = s.slice(prefix.length)
      if (dict[rest] !== undefined) return `${dict[prefix]}${dict[rest]}`
    }
  }
  return s
}

/** 直接给出中英两个文案（不查词典）。 */
export function tf(zh: string, en: string): string {
  return langNow === 'en' ? en : zh
}

export function currentLang(): Lang {
  return langNow
}

interface Prefs {
  theme: Theme
  lang: Lang
  toggleTheme: () => void
  toggleLang: () => void
}

const Ctx = createContext<Prefs>({ theme: 'light', lang: 'zh', toggleTheme: () => {}, toggleLang: () => {} })

function initialTheme(): Theme {
  const saved = localStorage.getItem(THEME_KEY) as Theme | null
  if (saved === 'light' || saved === 'dark') return saved
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(initialTheme)
  const [lang, setLang] = useState<Lang>(langNow)

  // 渲染期同步更新模块级语言：子组件在同一次渲染里就能读到新值
  langNow = lang

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.style.colorScheme = theme
    localStorage.setItem(THEME_KEY, theme)
  }, [theme])

  useEffect(() => {
    document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN'
    localStorage.setItem(LANG_KEY, lang)
  }, [lang])

  return (
    <Ctx.Provider value={{
      theme, lang,
      toggleTheme: () => setTheme((v) => (v === 'light' ? 'dark' : 'light')),
      toggleLang: () => setLang((v) => (v === 'zh' ? 'en' : 'zh')),
    }}>
      {children}
    </Ctx.Provider>
  )
}

export const usePrefs = () => useContext(Ctx)
