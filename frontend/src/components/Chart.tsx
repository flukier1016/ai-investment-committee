import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import { usePrefs } from '../prefs'

interface Props {
  option: echarts.EChartsOption
  height?: number | string
  onClick?: (params: echarts.ECElementEvent) => void
}

export default function Chart({ option, height = 300, onClick }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
  const { theme } = usePrefs()

  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current, theme === 'dark' ? 'dark' : undefined)
    chartRef.current = chart
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.dispose()
      chartRef.current = null
    }
  }, [theme])

  useEffect(() => {
    // 暗色主题自带深底色，统一改为透明由页面卡片承接
    chartRef.current?.setOption({ backgroundColor: 'transparent', ...option }, { notMerge: true })
  }, [option, theme])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart || !onClick) return
    chart.on('click', onClick)
    return () => {
      chart.off('click')
    }
  }, [onClick, theme])

  return <div ref={ref} style={{ width: '100%', height }} />
}
