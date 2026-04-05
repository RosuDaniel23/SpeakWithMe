import { useState, useEffect, useCallback } from 'react';
import useEyeTracking from '@/lib/useEyeTracking';
import { api } from '@/lib/api';

// Target order & labels matching Python plus neutral center (top, bottom, right, left, center)
const TARGET_ORDER = [0,1,2,3,4];
const TARGET_LABEL: Record<number,string> = {0:'Top',1:'Bottom',2:'Right',3:'Left',4:'Center'};

interface Props { onDone: () => void; minSamplesPerTarget?: number; }

export default function CalibrationPage({ onDone, minSamplesPerTarget = 1 }: Props) {
  const eye = useEyeTracking();
  const [currentIdx,setCurrentIdx] = useState(0); // index inside TARGET_ORDER
  const [samplesPerTarget,setSamplesPerTarget] = useState<Record<number,number>>({0:0,1:0,2:0,3:0,4:0});
  const [statusMsg,setStatusMsg] = useState('');
  const [busy,setBusy] = useState(false);
  const [computed,setComputed] = useState(false);
  const [hasPrevCalib,setHasPrevCalib] = useState(false);

  // Helpers for positioning: replicate Python margins (8% of width/height)
  const marginStyles = (target:number): React.CSSProperties => {
    const vw = typeof window !== 'undefined' ? window.innerWidth : 1920;
    const vh = typeof window !== 'undefined' ? window.innerHeight : 1080;
    const mx = vw * 0.08;
    const my = vh * 0.08;
    switch(target){
      case 0: return { left: '50%', top: `${my}px`, transform:'translateX(-50%)'}; // top center
      case 1: return { left: '50%', top: `${vh - my}px`, transform:'translate(-50%, -100%)'}; // bottom center
      case 2: return { left: `${vw - mx}px`, top: '50%', transform:'translate(-100%, -50%)'}; // right center
      case 3: return { left: `${mx}px`, top: '50%', transform:'translate(0,-50%)'}; // left center
      case 4: return { left: '50%', top: '50%', transform:'translate(-50%,-50%)'}; // center
      default: return {};
    }
  };

  const applyTarget = useCallback(async (target:number) => {
    setBusy(true);
    try {
      await api('/calibration/target',{method:'POST', body:JSON.stringify({target_index: target})});
  setStatusMsg(`Target ${TARGET_LABEL[target]}: look at the green dot then press Sample.`);
    } catch(e:any){ setStatusMsg(e.message);} finally { setBusy(false);} 
  },[]);

  const startFreshCalibration = useCallback(async () => {
    setBusy(true);
    try {
      await api('/calibration/start?force=true', { method: 'POST' });
      setHasPrevCalib(false);
      setSamplesPerTarget({ 0: 0, 1: 0, 2: 0, 3: 0, 4: 0 });
      setCurrentIdx(0);
      setComputed(false);
      setStatusMsg('');
      await applyTarget(0);
    } catch (e: any) { setStatusMsg(e.message); }
    finally { setBusy(false); }
  }, [applyTarget]);

  // Start calibration on mount — use force=false so existing calibration is not wiped
  useEffect(() => {
    (async () => {
      try {
        const r = await api('/calibration/start', { method: 'POST' });
        if (r.skipped) {
          setHasPrevCalib(true);
          setStatusMsg('Previous calibration loaded. Use it or recalibrate below.');
        } else {
          await applyTarget(TARGET_ORDER[0]);
        }
      } catch (e: any) { setStatusMsg(e.message); }
    })();
  }, [applyTarget]);

  const nextTarget = async () => {
    const nextIdx = (currentIdx + 1) % TARGET_ORDER.length;
    setCurrentIdx(nextIdx);
    await applyTarget(TARGET_ORDER[nextIdx]);
  };

  const addSample = async () => {
    setBusy(true);
    try {
      const r = await api('/calibration/sample',{method:'POST'});
      setSamplesPerTarget(r.counts);
      setStatusMsg('Sample captured. You may add more or move to next target.');
    } catch(e:any){ setStatusMsg(e.message);} finally { setBusy(false);} 
  };

  const canCompute = TARGET_ORDER.every(t => samplesPerTarget[t] >= minSamplesPerTarget);

  const compute = async () => {
    if(!canCompute) return;
    setBusy(true);
    try { await api('/calibration/compute',{method:'POST'}); setComputed(true); setStatusMsg('Calibration complete. Loading app...'); setTimeout(()=>onDone(), 800); } catch(e:any){ setStatusMsg(e.message);} finally { setBusy(false);} 
  };

  // Keyboard shortcuts: Space = sample, C = compute (if ready), N = next
  useEffect(()=>{
    const handler = (e:KeyboardEvent) => {
      if(e.code === 'Space'){ e.preventDefault(); addSample(); }
      else if(e.key.toLowerCase()==='n'){ nextTarget(); }
      else if(e.key.toLowerCase()==='c'){ compute(); }
    };
    window.addEventListener('keydown', handler);
    return ()=> window.removeEventListener('keydown', handler);
  },[addSample, nextTarget, compute]);

  return (
    <div className="relative w-screen h-screen bg-black text-white overflow-hidden select-none">
      {/* Previous calibration overlay */}
      {hasPrevCalib && !computed && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-6 bg-black/90 z-10">
          <h2 className="text-2xl font-semibold">Previous Calibration Found</h2>
          <p className="text-sm opacity-70 text-center max-w-md">
            A calibration from a previous session is loaded. You can use it directly or run a fresh calibration.
          </p>
          <div className="flex gap-4">
            <button onClick={onDone} className="px-6 py-3 rounded bg-emerald-600 text-base font-medium">
              Use previous calibration
            </button>
            <button disabled={busy} onClick={startFreshCalibration} className="px-6 py-3 rounded bg-gray-700 text-base font-medium disabled:opacity-40">
              Recalibrate
            </button>
          </div>
        </div>
      )}
      {/* Instruction overlay */}
      <div className="absolute top-4 left-1/2 -translate-x-1/2 text-center px-4">
        <h1 className="text-2xl font-semibold tracking-tight">Calibration</h1>
        <p className="text-sm opacity-80 mt-1">
          Look steadily at the GREEN dot. Press <strong>Sample (Space)</strong> to record. Then <strong>Next (N)</strong> to move on. After at least {minSamplesPerTarget} sample per target press <strong>Compute (C)</strong>.
        </p>
        <p className="text-xs mt-1 opacity-60">{statusMsg}</p>
      </div>
      {/* Target dots */}
      {TARGET_ORDER.map(t => {
        const active = TARGET_ORDER[currentIdx] === t;
        const count = samplesPerTarget[t] || 0;
        return (
          <div key={t} style={marginStyles(t)} className="absolute flex flex-col items-center gap-1">
            <div className={`rounded-full transition-all ${active ? 'bg-green-400 scale-150 shadow-[0_0_20px_8px_rgba(0,255,0,0.3)]':'bg-red-500'} w-6 h-6`} />
            <span className="text-[10px] font-mono opacity-80">{TARGET_LABEL[t]} ({count})</span>
          </div>
        );
      })}
      {/* Bottom control bar */}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex gap-3">
        <button disabled={busy} onClick={addSample} className="px-4 py-2 rounded bg-blue-600 disabled:opacity-40 text-sm">Sample (Space)</button>
        <button disabled={busy} onClick={nextTarget} className="px-4 py-2 rounded bg-purple-600 disabled:opacity-40 text-sm">Next (N)</button>
        <button disabled={busy || !canCompute || computed} onClick={compute} className="px-4 py-2 rounded bg-emerald-600 disabled:opacity-30 text-sm">Compute (C)</button>
  <button disabled={busy} onClick={startFreshCalibration} className="px-4 py-2 rounded bg-gray-700 disabled:opacity-40 text-sm">Reset</button>
      </div>
      <div className="absolute bottom-2 right-3 text-[10px] opacity-50">Tracking: {eye.eye_tracking_status}</div>
    </div>
  );
}