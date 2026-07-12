import { useRef, useState, useEffect } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useAnalyzeSkin } from '@/hooks/useSkinAnalysis'
import { useSession } from '@/lib/sessionContext'
import type { SkinAnalysisResult } from '@/lib/api'

const SESSION_KEY = 'derma6:skin-analysis'

function readSession(): { result: SkinAnalysisResult; imageDataUrl: string } | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function writeSession(result: SkinAnalysisResult, imageDataUrl: string) {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify({ result, imageDataUrl }))
}

function clearSession() {
  sessionStorage.removeItem(SESSION_KEY)
}

export default function SkinAnalysisPage() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  // Restore last result when navigating back to this page
  const [preview, setPreview] = useState<string | null>(() => readSession()?.imageDataUrl ?? null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [result, setResult] = useState<SkinAnalysisResult | null>(() => readSession()?.result ?? null)
  const [cameraOpen, setCameraOpen] = useState(false)

  const analyze = useAnalyzeSkin()
  const navigate = useNavigate()
  const { startNewSession } = useSession()

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    applyFile(file)
  }

  function applyFile(file: File) {
    setSelectedFile(file)
    setResult(null)
    clearSession()
    const reader = new FileReader()
    reader.onload = (e) => setPreview(e.target?.result as string)
    reader.readAsDataURL(file)
  }

  function handleCameraCapture(file: File) {
    setCameraOpen(false)
    applyFile(file)
  }

  async function handleAnalyze() {
    if (!selectedFile) return
    const data = await analyze.mutateAsync(selectedFile)
    setResult(data)
    if (preview) writeSession(data, preview)
  }

  function handleReset() {
    setPreview(null)
    setSelectedFile(null)
    setResult(null)
    clearSession()
    analyze.reset()
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  async function handleChatAbout(message: string) {
    await startNewSession()
    sessionStorage.setItem('derma6:initial-message', message)
    navigate({ to: '/chat' })
  }

  const confidencePct = result ? Math.round(result.confidence * 100) : 0
  const confidenceColor =
    confidencePct >= 75 ? '#7A9B7D' : confidencePct >= 50 ? '#B5A55A' : '#C07070'

  return (
    <PageShell>
      <h2 style={{ color: '#E0E8E0', fontSize: 20, fontWeight: 700, marginBottom: 4 }}>
        Skin Analysis
      </h2>
      <p style={{ color: '#9EAD9E', fontSize: 13, marginBottom: 24 }}>
        Upload or take a photo of your skin for AI-powered screening.
      </p>

      <input
        ref={fileInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        style={{ display: 'none' }}
        onChange={handleFileSelect}
      />

      {cameraOpen && (
        <CameraModal onCapture={handleCameraCapture} onClose={() => setCameraOpen(false)} />
      )}

      {/* Upload area */}
      {!preview && (
        <div
          className="flex flex-col items-center justify-center gap-4 rounded-2xl p-12 mb-6"
          style={{ border: '2px dashed #4B5A4C', background: '#2E3D2F' }}
        >
          <span style={{ fontSize: 48 }}>🔬</span>
          <p style={{ color: '#9EAD9E', fontSize: 14 }}>
            Select a clear photo of the affected skin area
          </p>
          <div className="flex gap-3">
            <Button
              onClick={() => fileInputRef.current?.click()}
              style={{ background: '#7A9B7D', color: '#1C2520', fontWeight: 600, cursor: 'pointer' }}
            >
              Upload Photo
            </Button>
            <Button
              onClick={() => setCameraOpen(true)}
              variant="outline"
              style={{ borderColor: '#4B5A4C', color: '#9EAD9E', background: 'transparent', cursor: 'pointer' }}
            >
              Take Photo
            </Button>
          </div>
        </div>
      )}

      {/* Preview + analyze */}
      {preview && !result && (
        <div className="flex flex-col items-center gap-4 mb-6">
          <img
            src={preview}
            alt="Selected skin"
            style={{
              maxWidth: 320,
              maxHeight: 320,
              borderRadius: 16,
              border: '2px solid #4B5A4C',
              objectFit: 'cover',
            }}
          />
          <div className="flex gap-3">
            <Button
              onClick={handleAnalyze}
              disabled={analyze.isPending}
              style={{ background: '#7A9B7D', color: '#1C2520', fontWeight: 600, cursor: 'pointer' }}
            >
              {analyze.isPending ? 'Analysing…' : 'Analyse'}
            </Button>
            <Button
              onClick={handleReset}
              variant="outline"
              style={{ borderColor: '#4B5A4C', color: '#9EAD9E', background: 'transparent', cursor: 'pointer' }}
            >
              Choose different photo
            </Button>
          </div>
          {analyze.isPending && (
            <p style={{ color: '#9EAD9E', fontSize: 13 }}>
              Running vision analysis, this may take a few seconds…
            </p>
          )}
        </div>
      )}

      {/* Error state */}
      {analyze.isError && (
        <div className="mb-6 p-4 rounded-xl" style={{ background: '#5A3E3E', border: '1px solid #7A4E4E' }}>
          <p style={{ color: '#F0B8B8', fontSize: 13 }}>
            ⚠️ {analyze.error?.message ?? 'Analysis failed. Please try again.'}
          </p>
          <button
            onClick={handleReset}
            style={{ color: '#9EAD9E', fontSize: 13, marginTop: 8, cursor: 'pointer', background: 'none', border: 'none' }}
          >
            Try again →
          </button>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="flex flex-col gap-4">
          {/* Image + primary result row */}
          <div className="flex gap-4 flex-wrap">
            <img
              src={preview!}
              alt="Analysed skin"
              style={{
                width: 140,
                height: 140,
                borderRadius: 12,
                border: '2px solid #4B5A4C',
                objectFit: 'cover',
                flexShrink: 0,
              }}
            />
            <Card style={{ background: '#2E3D2F', border: '1px solid #4B5A4C', flex: 1, minWidth: 200 }}>
              <CardHeader className="pb-1 pt-3 px-4">
                <CardTitle className="text-xs font-semibold tracking-widest uppercase" style={{ color: '#9EAD9E' }}>
                  Primary Finding
                </CardTitle>
              </CardHeader>
              <CardContent className="pb-3 px-4">
                <p style={{ color: '#E0E8E0', fontSize: 20, fontWeight: 700, marginBottom: 8 }}>
                  {result.condition}
                </p>
                <div style={{ marginBottom: 6 }}>
                  <div className="flex justify-between mb-1">
                    <span style={{ color: '#9EAD9E', fontSize: 11 }}>Confidence</span>
                    <span style={{ color: confidenceColor, fontSize: 11, fontWeight: 600 }}>
                      {confidencePct}%
                    </span>
                  </div>
                  <div style={{ background: '#1C2520', borderRadius: 4, height: 6, overflow: 'hidden' }}>
                    <div
                      style={{
                        width: `${confidencePct}%`,
                        height: '100%',
                        background: confidenceColor,
                        borderRadius: 4,
                        transition: 'width 0.5s ease',
                      }}
                    />
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Reasoning */}
          <Card style={{ background: '#2E3D2F', border: '1px solid #4B5A4C' }}>
            <CardHeader className="pb-1 pt-3 px-4">
              <CardTitle className="text-xs font-semibold tracking-widest uppercase" style={{ color: '#9EAD9E' }}>
                Analysis Notes
              </CardTitle>
            </CardHeader>
            <CardContent className="pb-3 px-4">
              <p style={{ color: '#E0E8E0', fontSize: 14, lineHeight: 1.6 }}>{result.reasoning}</p>
            </CardContent>
          </Card>

          {/* Alternatives */}
          {result.alternatives.length > 0 && (
            <Card style={{ background: '#2E3D2F', border: '1px solid #4B5A4C' }}>
              <CardHeader className="pb-1 pt-3 px-4">
                <CardTitle className="text-xs font-semibold tracking-widest uppercase" style={{ color: '#9EAD9E' }}>
                  Differential Diagnoses
                </CardTitle>
              </CardHeader>
              <CardContent className="pb-3 px-4">
                <div className="flex flex-col gap-1">
                  {result.alternatives.map((alt) => (
                    <div key={alt.condition} className="flex justify-between">
                      <span style={{ color: '#E0E8E0', fontSize: 13 }}>{alt.condition}</span>
                      <span style={{ color: '#9EAD9E', fontSize: 13 }}>{alt.probability}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Disclaimer */}
          <div className="p-3 rounded-xl" style={{ background: '#3A3A2E', border: '1px solid #5A5A3E' }}>
            <p style={{ color: '#C8C890', fontSize: 12, lineHeight: 1.5 }}>
              ⚠️ {result.disclaimer}
            </p>
          </div>

          {/* Chat actions — hidden when result is unclear */}
          {result.condition.toLowerCase() !== 'unclear' && <div className="flex flex-col gap-2">
            <p className="text-xs font-semibold tracking-widest uppercase" style={{ color: '#9EAD9E' }}>
              Continue in Chat
            </p>
            <div className="grid grid-cols-2 gap-2">
              {[
                {
                  label: 'Tell me more about this',
                  message: `I just got my skin analysis result: ${result.condition} (${confidencePct}% confidence). The model's reasoning: "${result.reasoning}" Can you explain what this condition means for my skin?`,
                },
                {
                  label: 'Suggest a routine',
                  message: `My skin analysis detected ${result.condition} (${confidencePct}% confidence). The model's reasoning: "${result.reasoning}" Can you build me a skincare routine tailored to this condition?`,
                },
                {
                  label: 'Ingredients to avoid',
                  message: `My skin analysis detected ${result.condition} (${confidencePct}% confidence). The model's reasoning: "${result.reasoning}" What ingredients should I avoid, and are there any common ingredient conflicts I should know about?`,
                },
                {
                  label: 'Should I see a doctor?',
                  message: `My skin analysis detected ${result.condition} (${confidencePct}% confidence). The model's reasoning: "${result.reasoning}" How serious is this typically, and should I consult a dermatologist?`,
                },
              ].map(({ label, message }) => (
                <button
                  key={label}
                  onClick={() => handleChatAbout(message)}
                  className="px-3 py-2 rounded-xl text-xs text-left transition-opacity hover:opacity-80"
                  style={{ background: '#2E3D2F', border: '1px solid #4B5A4C', color: '#E0E8E0', cursor: 'pointer' }}
                >
                  {label} →
                </button>
              ))}
            </div>
          </div>}

          {/* Actions */}
          <div className="flex items-center gap-4 flex-wrap">
            <Button
              onClick={handleReset}
              variant="outline"
              style={{ borderColor: '#4B5A4C', color: '#9EAD9E', background: 'transparent', cursor: 'pointer' }}
            >
              Analyse another photo →
            </Button>
            <button
              onClick={() => navigate({ to: '/profile' })}
              style={{ color: '#9EAD9E', fontSize: 13, cursor: 'pointer', background: 'none', border: 'none', textDecoration: 'underline' }}
            >
              View history in profile →
            </button>
          </div>
        </div>
      )}
    </PageShell>
  )
}

function CameraModal({ onCapture, onClose }: {
  onCapture: (file: File) => void
  onClose: () => void
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [stream, setStream] = useState<MediaStream | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: 'environment' }, audio: false })
      .then(s => {
        if (!active) { s.getTracks().forEach(t => t.stop()); return }
        setStream(s)
        if (videoRef.current) videoRef.current.srcObject = s
      })
      .catch(err => {
        if (!active) return
        setError(
          err.name === 'NotAllowedError'
            ? 'Camera permission denied. Allow camera access and try again.'
            : 'Camera not available on this device.'
        )
      })
    return () => { active = false }
  }, [])

  useEffect(() => {
    return () => { stream?.getTracks().forEach(t => t.stop()) }
  }, [stream])

  function capture() {
    const video = videoRef.current
    if (!video) return
    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    canvas.getContext('2d')!.drawImage(video, 0, 0)
    canvas.toBlob(blob => {
      if (!blob) return
      const file = new File([blob], `photo_${Date.now()}.jpg`, { type: 'image/jpeg' })
      stream?.getTracks().forEach(t => t.stop())
      onCapture(file)
    }, 'image/jpeg', 0.92)
  }

  function close() {
    stream?.getTracks().forEach(t => t.stop())
    onClose()
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.88)',
        zIndex: 50, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center', gap: 20,
      }}
    >
      {error ? (
        <div style={{ color: '#F0B8B8', textAlign: 'center', padding: 24, maxWidth: 320 }}>
          <p style={{ fontSize: 15, marginBottom: 16 }}>⚠️ {error}</p>
          <Button
            onClick={close}
            variant="outline"
            style={{ borderColor: '#4B5A4C', color: '#9EAD9E', background: 'transparent', cursor: 'pointer' }}
          >
            Close
          </Button>
        </div>
      ) : (
        <>
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            style={{
              borderRadius: 12,
              maxWidth: '90vw',
              maxHeight: '60vh',
              background: '#1C2520',
              display: 'block',
            }}
          />
          <div style={{ display: 'flex', gap: 12 }}>
            <Button
              onClick={capture}
              disabled={!stream}
              style={{ background: '#7A9B7D', color: '#1C2520', fontWeight: 600, cursor: 'pointer' }}
            >
              📸 Capture
            </Button>
            <Button
              onClick={close}
              variant="outline"
              style={{ borderColor: '#4B5A4C', color: '#9EAD9E', background: 'transparent', cursor: 'pointer' }}
            >
              Cancel
            </Button>
          </div>
        </>
      )}
    </div>
  )
}

function PageShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex-1 overflow-y-auto p-6" style={{ background: '#3E4D3F' }}>
      <div style={{ maxWidth: 640 }}>
        {children}
      </div>
    </div>
  )
}
