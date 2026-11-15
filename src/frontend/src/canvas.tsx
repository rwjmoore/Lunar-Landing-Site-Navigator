import { useEffect, useRef, type ComponentProps } from 'react'

type Paint = (context: CanvasRenderingContext2D, width: number, height: number) => void

export function Canvas({ paint, ...props }: ComponentProps<'canvas'> & { paint: Paint }) {
  const element = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = element.current
    const context = canvas?.getContext('2d')
    if (!canvas || !context) return
    function render() {
      if (!canvas || !context) return
      const { width, height } = canvas.getBoundingClientRect()
      if (width < 1 || height < 1) return
      const ratio = window.devicePixelRatio || 1
      const pixelWidth = Math.round(width * ratio)
      const pixelHeight = Math.round(height * ratio)
      if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
        canvas.width = pixelWidth
        canvas.height = pixelHeight
      }
      context.setTransform(pixelWidth / width, 0, 0, pixelHeight / height, 0, 0)
      context.clearRect(0, 0, width, height)
      context.save()
      paint(context, width, height)
      context.restore()
    }
    render()
    const resize = new ResizeObserver(render)
    resize.observe(canvas)
    return () => resize.disconnect()
  }, [paint])
  return <canvas ref={element} {...props} />
}
