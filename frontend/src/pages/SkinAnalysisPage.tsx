import { useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useAnalyzeSkin, useSaveMedicalFlag } from '@/hooks/useSkinAnalysis'
import type { SkinAnalysisResult } from '@/lib/api'

export default function SkinAnalysisPage() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const cameraInputRef = useRef<HTMLInputElement>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [result, setResult] = useState<SkinAnalysisResult | null>(null)
  const [saved, setSaved] = useState(false)

  const analyze = useAnalyzeSkin()
  const saveFlag = useSaveMedicalFlag()
  const navigate = useNavigate()

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setSelectedFile(file)
    setResult(null)
    setSaved(false)
    const url = URL.createObjectURL(file)
    setPreview(url)
  }

  async function handleAnalyze() {
    if (!selectedFile) return
    const data = await analyze.mutateAsync(selectedFile)
    setResult(data)
  }

  async function handleSaveToProfile() {
    if (!result) return
    await saveFlag.mutateAsync(result.condition)
    setSaved(true)
  }

  function handleReset() {
    setPreview(null)
    setSelectedFile(null)
    setResult(null)
    setSaved(false)
    analyze.reset()
    if (fileInputRef.current) fileInputRef.current.value = ''
    if (cameraInputRef.current) cameraInputRef.current.value = ''
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

      {/* Hidden inputs */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        style={{ display: 'none' }}
        onChange={handleFileSelect}
      />
      <input
        ref={cameraInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        style={{ display: 'none' }}
        onChange={handleFileSelect}
      />

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
              onClick={() => cameraInputRef.current?.click()}
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
                {/* Confidence bar */}
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

          {/* Actions */}
          <div className="flex gap-3 flex-wrap">
            {!saved ? (
              <Button
                onClick={handleSaveToProfile}
                disabled={saveFlag.isPending}
                style={{ background: '#7A9B7D', color: '#1C2520', fontWeight: 600, cursor: 'pointer' }}
              >
                {saveFlag.isPending ? 'Saving…' : 'Save to My Profile'}
              </Button>
            ) : (
              <div className="flex items-center gap-2">
                <span style={{ color: '#7A9B7D', fontSize: 14 }}>✅ Saved to profile</span>
                <button
                  onClick={() => navigate({ to: '/profile' })}
                  style={{ color: '#9EAD9E', fontSize: 13, cursor: 'pointer', background: 'none', border: 'none', textDecoration: 'underline' }}
                >
                  View profile →
                </button>
              </div>
            )}
            <Button
              onClick={handleReset}
              variant="outline"
              style={{ borderColor: '#4B5A4C', color: '#9EAD9E', background: 'transparent', cursor: 'pointer' }}
            >
              Analyse another photo
            </Button>
          </div>

          {saveFlag.isError && (
            <p style={{ color: '#F0B8B8', fontSize: 13 }}>
              ⚠️ {saveFlag.error?.message ?? 'Could not save. Please try again.'}
            </p>
          )}
        </div>
      )}
    </PageShell>
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
