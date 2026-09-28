/**
 * ECharts 生命周期封装。
 *
 * 只做三件事：初始化、跟随容器尺寸、卸载时销毁。**不负责** option 的更新策略 ——
 * 那属于具体图表，因为不同图表对"数据变了"和"形态变了"的处理不一样
 * （K 线图必须保住用户的缩放状态，折线图则无所谓）。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts/core'

export interface ChartHandle {
  containerRef: React.RefObject<HTMLDivElement>
  /** 拿到底层实例；未挂载时返回 null。 */
  instance: () => echarts.ECharts | null
  /** 实例就绪后自增。effect 依赖它即可安全地访问实例。 */
  ready: number
}

export function useChart(): ChartHandle {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
  const [ready, setReady] = useState(0)

  // 必须是稳定引用：否则每个 effect 的依赖里带上它就会每渲染都重跑。
  const instance = useCallback(() => chartRef.current, [])

  useEffect(() => {
    const element = containerRef.current
    if (!element) return

    const chart = echarts.init(element, undefined, { renderer: 'canvas' })
    chartRef.current = chart
    setReady((value) => value + 1)

    // 侧栏折叠、窗口缩放、字体变化都会改变容器尺寸。
    const observer = new ResizeObserver(() => {
      // 容器被隐藏（display:none）时宽高为 0，此时 resize 会把图表压扁。
      if (element.clientWidth > 0 && element.clientHeight > 0) chart.resize()
    })
    observer.observe(element)

    return () => {
      observer.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  return {
    containerRef,
    instance,
    ready,
  }
}
