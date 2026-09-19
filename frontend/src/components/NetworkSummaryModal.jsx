import React, { useState, useEffect } from 'react';
import { X, Layers } from 'lucide-react';

export default function NetworkSummaryModal({ isOpen, onClose, onSubmitFilter, selectedDiscom = 'TPWODL' }) {
  const [formData, setFormData] = useState({
    circle: '',
    division: '',
    subdivision: '',
    section: '',
    gss: '',
    hv_feeder: '',
    pss: '',
    mv_feeder: '',
    dss: '',
    lv_feeder: ''
  });

  const [options, setOptions] = useState({
    circle: [],
    division: [],
    subdivision: [],
    section: [],
    gss: [],
    hv_feeder: [],
    pss: [],
    mv_feeder: [],
    dss: [],
    lv_feeder: []
  });

  const [loading, setLoading] = useState(false);

  // Fetch cascading dropdown options when parent selections change
  useEffect(() => {
    if (!isOpen) return;

    const fetchOptions = async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams();
        params.append('discom', selectedDiscom);
        if (formData.circle) params.append('circle', formData.circle);
        if (formData.division) params.append('division', formData.division);
        if (formData.subdivision) params.append('subdivision', formData.subdivision);
        if (formData.section) params.append('section', formData.section);
        if (formData.gss) params.append('gss', formData.gss);
        if (formData.hv_feeder) params.append('hv_feeder', formData.hv_feeder);
        if (formData.pss) params.append('pss', formData.pss);
        if (formData.mv_feeder) params.append('mv_feeder', formData.mv_feeder);
        if (formData.dss) params.append('dss', formData.dss);

        const res = await fetch(`/api/hierarchy/network-summary/options?${params.toString()}`);
        const data = await res.json();
        if (data && data.status === 'success') {
          setOptions({
            circle: data.circle || [],
            division: data.division || [],
            subdivision: data.subdivision || [],
            section: data.section || [],
            gss: data.gss || [],
            hv_feeder: data.hv_feeder || [],
            pss: data.pss || [],
            mv_feeder: data.mv_feeder || [],
            dss: data.dss || [],
            lv_feeder: data.lv_feeder || []
          });
        }
      } catch (err) {
        console.error('Failed to fetch cascading network summary options:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchOptions();
  }, [
    isOpen,
    formData.circle,
    formData.division,
    formData.subdivision,
    formData.section,
    formData.gss,
    formData.hv_feeder,
    formData.pss,
    formData.mv_feeder,
    formData.dss
  ]);

  const handleChange = (field, value) => {
    setFormData((prev) => {
      const next = { ...prev, [field]: value };
      // Cascade-reset dependent child fields on parent selection change
      if (field === 'circle') {
        next.division = '';
        next.subdivision = '';
        next.section = '';
        next.gss = '';
        next.hv_feeder = '';
        next.pss = '';
        next.mv_feeder = '';
        next.dss = '';
        next.lv_feeder = '';
      } else if (field === 'division') {
        next.subdivision = '';
        next.section = '';
        next.gss = '';
        next.hv_feeder = '';
        next.pss = '';
        next.mv_feeder = '';
        next.dss = '';
        next.lv_feeder = '';
      } else if (field === 'gss') {
        next.hv_feeder = '';
        next.pss = '';
        next.mv_feeder = '';
        next.dss = '';
        next.lv_feeder = '';
      } else if (field === 'pss') {
        next.mv_feeder = '';
        next.dss = '';
        next.lv_feeder = '';
      }
      return next;
    });
  };

  const handleClear = () => {
    setFormData({
      circle: '',
      division: '',
      subdivision: '',
      section: '',
      gss: '',
      hv_feeder: '',
      pss: '',
      mv_feeder: '',
      dss: '',
      lv_feeder: ''
    });
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (onSubmitFilter) {
      onSubmitFilter(formData);
    }
    onClose();
  };

  if (!isOpen) return null;

  const rows = [
    { label: 'Circle :', field: 'circle', placeholder: '-- Select Circle --', opts: options.circle },
    { label: 'Division :', field: 'division', placeholder: '-- Select Division --', opts: options.division },
    { label: 'Sub Division :', field: 'subdivision', placeholder: '-- Select Sub-Division --', opts: options.subdivision },
    { label: 'Section :', field: 'section', placeholder: '-- Select Section --', opts: options.section },
    { label: 'GSS :', field: 'gss', placeholder: '-- Select GSS --', opts: options.gss },
    { label: 'HV feeder :', field: 'hv_feeder', placeholder: '-- Select HV feeder --', opts: options.hv_feeder },
    { label: 'PSS :', field: 'pss', placeholder: '-- Select PSS --', opts: options.pss },
    { label: 'MV feeder :', field: 'mv_feeder', placeholder: '-- Select MV feeder --', opts: options.mv_feeder },
    { label: 'DSS :', field: 'dss', placeholder: '-- Select DSS --', opts: options.dss },
    { label: 'LV feeder :', field: 'lv_feeder', placeholder: '-- Select LV feeder --', opts: options.lv_feeder },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4">
      <div className="w-full max-w-md bg-white rounded-lg shadow-2xl overflow-hidden border border-slate-200 text-slate-800 font-sans text-sm animate-in fade-in zoom-in-95 duration-150">
        {/* Header Bar */}
        <div className="flex items-center justify-between px-5 py-3.5 bg-slate-100 border-b border-slate-200">
          <div className="flex items-center space-x-2">
            <Layers className="w-5 h-5 text-sky-600" />
            <h2 className="text-lg font-semibold text-slate-800">Network Summary</h2>
          </div>
          <button
            onClick={onClose}
            type="button"
            className="p-1 rounded text-slate-400 hover:text-slate-600 hover:bg-slate-200 transition"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Cascading Form Body */}
        <form onSubmit={handleSubmit} className="p-6 space-y-3">
          {rows.map(({ label, field, placeholder, opts }) => (
            <div key={field} className="grid grid-cols-12 items-center gap-2">
              <label className="col-span-4 text-xs font-bold text-slate-800 tracking-tight">
                {label}
              </label>
              <div className="col-span-8">
                <select
                  value={formData[field]}
                  onChange={(e) => handleChange(field, e.target.value)}
                  className="w-full bg-white border border-slate-300 rounded px-2.5 py-1 text-xs text-slate-700 shadow-inner focus:outline-hidden focus:border-sky-500 focus:ring-1 focus:ring-sky-500 transition"
                >
                  <option value="">{placeholder}</option>
                  {(Array.isArray(opts) ? opts : []).map((opt, idx) => {
                    const val = typeof opt === 'object' && opt !== null ? (opt.name || opt.id || JSON.stringify(opt)) : opt;
                    return (
                      <option key={`${val}-${idx}`} value={val}>
                        {val}
                      </option>
                    );
                  })}
                </select>
              </div>
            </div>
          ))}

          {/* Footer Notice and Actions */}
          <div className="pt-4 border-t border-slate-200 flex items-center justify-between">
            <span className="text-xs font-bold text-red-600">
              Note: This tool is under testing
            </span>
            <div className="flex items-center space-x-2">
              <button
                type="button"
                onClick={handleClear}
                className="px-3.5 py-1 text-xs font-medium text-white bg-sky-600 hover:bg-sky-700 rounded transition shadow-xs"
              >
                clear
              </button>
              <button
                type="submit"
                className="px-3.5 py-1 text-xs font-medium text-white bg-[#0284c7] hover:bg-[#0369a1] rounded transition shadow-xs"
              >
                Submit
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
