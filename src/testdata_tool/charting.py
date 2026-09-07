"""Interactive, offline chart helpers for consolidated test data."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import escape
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
from plotly.offline.offline import get_plotlyjs

from .normalize import normalize_header


PLOT_HEIGHT = 500
RANGE_SLIDER_THICKNESS = 0.22
QUICK_EXPORT_WIDTH_PX = 900
QUICK_EXPORT_HEIGHT_PX = 3600


@dataclass(frozen=True)
class ChartDefinition:
    """A serialisable Plotly chart plus its independent vertical bounds."""

    chart_id: str
    title: str
    figure: dict[str, Any]
    y_bounds: tuple[float, float]


def _channel_key(value: str) -> str:
    return re.sub(r"[\s_./\\-]+", " ", normalize_header(value)).strip()


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value)


def _matches_keyword(key: str, keyword: str) -> bool:
    keyword = _channel_key(keyword)
    if not keyword:
        return False
    if len(keyword) <= 2 and keyword.isascii():
        return keyword in re.findall(r"[a-z]+", key)
    compact_keyword = _compact(keyword)
    # CJK terms (for example "温度") intentionally have no ASCII compact form.
    # Comparing an empty string would otherwise mark every channel as temperature.
    if compact_keyword:
        return compact_keyword in _compact(key)
    return keyword in key


def _unit_matches(key: str, configured_units: set[str]) -> bool:
    for content in re.findall(r"[\[\(\{]([^\]\)\}]*)[\]\)\}]", key):
        if _compact(content) in configured_units:
            return True
    return False


def coerce_chart_numeric(values: pd.Series) -> pd.Series:
    """Coerce common spreadsheet numeric text without changing source values.

    The consolidated dataset remains untouched.  This conversion exists solely
    for deciding whether a channel can be drawn and for feeding Plotly a number.
    It accepts full-width characters, ordinary thousands separators and decimal
    commas such as ``12,5``.
    """
    if pd.api.types.is_numeric_dtype(values):
        return pd.to_numeric(values, errors="coerce")
    text = values.astype("string").str.normalize("NFKC").str.strip()
    has_dot = text.str.contains(r"\.", regex=True, na=False)
    comma_count = text.str.count(",")
    decimal_comma = (~has_dot) & (comma_count == 1) & text.str.match(
        r"^[+-]?\d+,\d+$", na=False
    )
    text = text.mask(decimal_comma, text.str.replace(",", ".", regex=False))
    text = text.str.replace(",", "", regex=False).str.replace(" ", "", regex=False)
    return pd.to_numeric(text, errors="coerce")


def has_chart_numeric_values(values: pd.Series) -> bool:
    """Whether a column has at least one finite value that Plotly can draw."""
    numeric = coerce_chart_numeric(values).to_numpy(dtype=float, na_value=np.nan)
    return bool(np.isfinite(numeric).any())


def classify_channels(
    channels: list[str], temperature_rules: dict[str, Any] | None = None
) -> tuple[list[str], list[str]]:
    """Return selected channels in temperature and non-temperature order.

    Matching is deliberately configuration driven so new test benches can extend
    the vocabulary without changing the visualisation code.
    """
    rules = temperature_rules or {}
    name_contains = [str(item) for item in rules.get("name_contains", [])]
    name_equals = {_channel_key(str(item)) for item in rules.get("name_equals", [])}
    name_prefixes = [_channel_key(str(item)) for item in rules.get("name_prefixes", [])]
    numeric_prefixes = {
        _compact(str(item))
        for item in rules.get("numeric_prefixes", ["t", "ts", "tck"])
    }
    units = {_compact(str(item)) for item in rules.get("units", [])}

    temperature: list[str] = []
    other: list[str] = []
    name_patterns = [str(item) for item in rules.get("name_patterns", [])]
    compiled_patterns = []
    for pattern in name_patterns:
        try:
            compiled_patterns.append(re.compile(pattern, re.IGNORECASE))
        except re.error:
            # A locally customised config must not make the chart unavailable.
            continue

    for channel in channels:
        key = _channel_key(channel)
        compact_key = _compact(key)
        numeric_match = re.match(r"^([a-z]+)\s*\d", key)
        numeric_prefix = _compact(numeric_match.group(1)) if numeric_match else ""
        is_temperature = (
            key in name_equals
            or any(_matches_keyword(key, keyword) for keyword in name_contains)
            or any(key == prefix or key.startswith(f"{prefix} ") for prefix in name_prefixes)
            or any(pattern.search(key) for pattern in compiled_patterns)
            or _unit_matches(key, units)
            or bool(numeric_prefix and numeric_prefix in numeric_prefixes)
            or compact_key in numeric_prefixes
        )
        (temperature if is_temperature else other).append(channel)
    return temperature, other


def _y_bounds(values: pd.Series) -> tuple[float, float]:
    finite = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return (0.0, 1.0)
    low, high = float(np.min(finite)), float(np.max(finite))
    if low == high:
        padding = max(abs(low) * 0.05, 1.0)
    else:
        padding = (high - low) * 0.03
    return (low - padding, high + padding)


def build_chart_definition(
    frame: pd.DataFrame, channels: list[str], chart_id: str, title: str
) -> ChartDefinition | None:
    """Build one line chart from a shared frame containing every selected row."""
    if not channels or frame.empty:
        return None
    plot_frame = frame[["__axis_value", "__source_id", *channels]].copy()
    for channel in channels:
        plot_frame[channel] = coerce_chart_numeric(plot_frame[channel])
    long_frame = plot_frame.melt(
        id_vars=["__axis_value", "__source_id"],
        value_vars=channels,
        var_name="通道",
        value_name="数值",
    ).dropna(subset=["__axis_value", "数值"])
    if long_frame.empty:
        return None

    figure = px.line(
        long_frame,
        x="__axis_value",
        y="数值",
        color="通道",
        line_group="__source_id",
        hover_data=["__source_id"],
        title=title,
    )
    figure.update_layout(
        height=PLOT_HEIGHT,
        margin={"l": 65, "r": 12, "t": 52, "b": 26},
        hovermode="x unified",
        legend={"title": {"text": "通道"}, "orientation": "h", "y": 1.12},
        uirevision=chart_id,
    )
    figure.update_xaxes(
        title="时间 / 循环 / 频率",
        rangeslider={
            "visible": True,
            "thickness": RANGE_SLIDER_THICKNESS,
            "bgcolor": "#f4f8fb",
            "bordercolor": "#8da5b7",
            "borderwidth": 1,
            # Keep the miniature trend an all-data overview even when the main
            # y-axis is narrowed through the vertical control.
            "yaxis": {"rangemode": "auto"},
        },
        showgrid=True,
    )
    figure.update_yaxes(title="数值", fixedrange=False, showgrid=True, zeroline=True)
    return ChartDefinition(
        chart_id=chart_id,
        title=title,
        figure=json.loads(figure.to_json()),
        y_bounds=_y_bounds(long_frame["数值"]),
    )


def build_chart_definitions(
    frame: pd.DataFrame, channels: list[str], temperature_rules: dict[str, Any] | None
) -> list[ChartDefinition]:
    """Split selected channels and return only groups with drawable data."""
    temperature, other = classify_channels(channels, temperature_rules)
    definitions = [
        build_chart_definition(frame, temperature, "temperature-chart", "温度通道"),
        build_chart_definition(frame, other, "other-chart", "其他通道"),
    ]
    return [item for item in definitions if item is not None]


def build_linked_chart_html(
    definitions: list[ChartDefinition], *, cycles_quick_export: bool = False
) -> str:
    """Create an offline Plotly component with linked x ranges and y controls."""
    payload = [
        {
            "id": item.chart_id,
            "title": item.title,
            "figure": item.figure,
            "bounds": list(item.y_bounds),
        }
        for item in definitions
    ]
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    cards = "".join(
        f'<section class="chart-card"><div class="plot" id="{escape(item.chart_id)}"></div>'
        f'<aside class="vertical-control" data-chart="{escape(item.chart_id)}" '
        f'aria-label="{escape(item.title)} 纵轴范围"></aside></section>'
        for item in definitions
    )
    return """<!doctype html>
<html><head><meta charset="utf-8" />
<style>
html,body{margin:0;padding:0;background:transparent;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
.chart-card{display:grid;grid-template-columns:minmax(0,1fr) 58px;gap:5px;align-items:stretch;margin:0 0 12px}
.plot{min-width:0;border:1px solid #d7e1e8;border-radius:7px;background:#fff;overflow:hidden}
.vertical-control{position:relative;min-height:460px;touch-action:none;user-select:none;color:#425466}
.vertical-track{position:absolute;left:21px;top:28px;bottom:28px;width:12px;border:1px solid #9aabba;border-radius:8px;background:#f0f5f8}
.vertical-selection{position:absolute;left:22px;width:10px;border-radius:7px;background:rgba(10,94,142,.34);cursor:grab}
.vertical-handle{position:absolute;left:15px;width:24px;height:10px;border:1px solid #0a5e8e;border-radius:5px;background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.2);cursor:ns-resize;transform:translateY(-50%)}
.vertical-label{position:absolute;left:0;width:58px;font-size:10px;line-height:12px;text-align:center;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#425466;transform:translateY(-50%)}
.vertical-label.high{top:13px}.vertical-label.low{bottom:1px;transform:none}
.quick-export{margin:0 0 6px;padding:8px 13px;border:1px solid #0a5e8e;border-radius:6px;background:#0a5e8e;color:white;font:600 13px system-ui,-apple-system,"Segoe UI",sans-serif;cursor:pointer}
.quick-export:hover{background:#074b70}.quick-export:disabled{opacity:.62;cursor:wait}
@media(max-width:700px){.chart-card{grid-template-columns:minmax(0,1fr) 48px}.vertical-control{min-height:430px}.vertical-label{width:48px;font-size:9px}}
</style>
<script>__PLOTLY_JS__</script></head><body>
<main>__CARDS__<button class="quick-export" id="quick-export" type="button">__EXPORT_LABEL__</button></main>
<script>
const charts=__PAYLOAD__;
const graphById={};
let syncingX=false;
const quickExportCycles=__EXPORT_CYCLES__;
const numberFormat=value=>{
  if(!Number.isFinite(value)) return "—";
  const magnitude=Math.abs(value);
  if(magnitude && (magnitude>=1e5 || magnitude<1e-3)) return value.toExponential(3);
  return value.toLocaleString(undefined,{maximumFractionDigits:4});
};
const clamp=(value,low,high)=>Math.max(low,Math.min(high,value));

function installVerticalControl(chart,graph){
  const root=document.querySelector(`.vertical-control[data-chart="${chart.id}"]`);
  const bounds=chart.bounds.slice();
  let view=bounds.slice();
  root.innerHTML='<span class="vertical-label high"></span><div class="vertical-track"></div><div class="vertical-selection"></div><div class="vertical-handle high"></div><div class="vertical-handle low"></div><span class="vertical-label low"></span>';
  const selection=root.querySelector('.vertical-selection');
  const highHandle=root.querySelector('.vertical-handle.high');
  const lowHandle=root.querySelector('.vertical-handle.low');
  const highLabel=root.querySelector('.vertical-label.high');
  const lowLabel=root.querySelector('.vertical-label.low');
  const span=Math.max(bounds[1]-bounds[0],Number.EPSILON);
  const position=value=>((bounds[1]-value)/span)*100;
  const render=()=>{
    const high=position(view[1]), low=position(view[0]);
    selection.style.top=`${high}%`; selection.style.height=`${Math.max(low-high,0.6)}%`;
    highHandle.style.top=`${high}%`; lowHandle.style.top=`${low}%`;
    highLabel.textContent=numberFormat(view[1]); lowLabel.textContent=numberFormat(view[0]);
  };
  const apply=()=>{render(); Plotly.relayout(graph,{"yaxis.range":view.slice(),"yaxis.autorange":false});};
  const setView=range=>{
    if(!range || range.length!==2 || !Number.isFinite(Number(range[0])) || !Number.isFinite(Number(range[1]))) return;
    view=[clamp(Number(range[0]),bounds[0],bounds[1]),clamp(Number(range[1]),bounds[0],bounds[1])];
    if(view[1]<=view[0]) view=bounds.slice();
    render();
  };
  const valueAt=event=>{
    const rect=root.getBoundingClientRect();
    return clamp(bounds[1]-((event.clientY-28-rect.top)/Math.max(rect.height-56,1))*span,bounds[0],bounds[1]);
  };
  const begin=(mode,event)=>{
    event.preventDefault();
    const start=valueAt(event), startView=view.slice();
    const move=moveEvent=>{
      const value=valueAt(moveEvent), minimumGap=span/1000;
      if(mode==='high') view[1]=clamp(value,view[0]+minimumGap,bounds[1]);
      else if(mode==='low') view[0]=clamp(value,bounds[0],view[1]-minimumGap);
      else {
        const delta=value-start, width=startView[1]-startView[0];
        let low=startView[0]+delta;
        low=clamp(low,bounds[0],bounds[1]-width);
        view=[low,low+width];
      }
      apply();
    };
    const finish=()=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',finish);};
    window.addEventListener('pointermove',move);window.addEventListener('pointerup',finish,{once:true});
  };
  highHandle.addEventListener('pointerdown',event=>begin('high',event));
  lowHandle.addEventListener('pointerdown',event=>begin('low',event));
  selection.addEventListener('pointerdown',event=>begin('move',event));
  graph.on('plotly_relayout',event=>{
    if(event['yaxis.range[0]']!==undefined && event['yaxis.range[1]']!==undefined) setView([event['yaxis.range[0]'],event['yaxis.range[1]']]);
    else if(event['yaxis.range']!==undefined) setView(event['yaxis.range']);
    else if(event['yaxis.autorange']) setView(bounds);
  });
  render();
}

function installXLink(graph){
  graph.on('plotly_relayout',event=>{
    if(syncingX) return;
    const range=event['xaxis.range'] || (event['xaxis.range[0]']!==undefined?[event['xaxis.range[0]'],event['xaxis.range[1]']]:null);
    if(!range || range[0]===undefined || range[1]===undefined) {
      if(event['xaxis.autorange']) {
        syncingX=true;
        Promise.all(Object.values(graphById).filter(item=>item!==graph).map(item=>Plotly.relayout(item,{'xaxis.autorange':true}))).finally(()=>{syncingX=false;});
      }
      return;
    }
    syncingX=true;
    Promise.all(Object.values(graphById).filter(item=>item!==graph).map(item=>Plotly.relayout(item,{'xaxis.range':range}))).finally(()=>{syncingX=false;});
  });
}

const exportImage=(graph,width,height,range)=>{
  const holder=document.createElement('div');
  holder.style.cssText='position:fixed;left:-10000px;top:-10000px;width:'+width+'px;height:'+height+'px;background:#fff';
  document.body.appendChild(holder);
  const layout=JSON.parse(JSON.stringify(graph.layout));
  layout.width=width; layout.height=height;
  layout.margin={l:110,r:35,t:105,b:100};
  layout.font={size:20};
  layout.xaxis=Object.assign({},layout.xaxis,{rangeslider:{visible:false}});
  if(range) { layout.xaxis.range=range; layout.xaxis.autorange=false; }
  const data=JSON.parse(JSON.stringify(graph.data));
  return Plotly.newPlot(holder,data,layout,{displaylogo:false}).then(()=>Plotly.toImage(holder,{format:'png',width,height,scale:1})).finally(()=>{Plotly.purge(holder);holder.remove();});
};

const downloadQuickExport=async()=>{
  const button=document.getElementById('quick-export');
  button.disabled=true; const original=button.textContent; button.textContent='正在生成截图…';
  try{
    const graphs=Object.values(graphById);
    let range=null;
    if(graphs.length){
      const current=graphs[0]._fullLayout.xaxis.range;
      if(quickExportCycles && Number.isFinite(Number(current[0])) && Number.isFinite(Number(current[1]))) {
        const allAxisValues=graphs[0].data.flatMap(trace=>trace.x||[]).map(Number).filter(Number.isFinite);
        const loadedMaximum=allAxisValues.length?Math.max(...allAxisValues):Number(current[1]);
        range=[Number(current[0]),Math.min(Number(current[0])+10,loadedMaximum)];
      } else range=current.slice();
    }
    const panelHeight=Math.floor(__EXPORT_HEIGHT__/Math.max(graphs.length,1));
    const images=await Promise.all(graphs.map(graph=>exportImage(graph,__EXPORT_WIDTH__,panelHeight,range)));
    const canvas=document.createElement('canvas'); canvas.width=__EXPORT_WIDTH__; canvas.height=__EXPORT_HEIGHT__;
    const context=canvas.getContext('2d'); context.fillStyle='#fff'; context.fillRect(0,0,canvas.width,canvas.height);
    await Promise.all(images.map((source,index)=>new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>{context.drawImage(image,0,index*panelHeight);resolve();};image.onerror=reject;image.src=source;})));
    const link=document.createElement('a'); link.href=canvas.toDataURL('image/png');
    link.download=quickExportCycles?'trend-10-cycles.png':'trend-current-range.png';
    document.body.appendChild(link); link.click(); link.remove();
  }catch(error){ console.error(error); alert('截图生成失败，请稍后重试。'); }
  finally{button.disabled=false;button.textContent=original;}
};

Promise.all(charts.map(chart=>{
  const config={displaylogo:false,responsive:true,scrollZoom:true};
  return Plotly.newPlot(chart.id,chart.figure.data,chart.figure.layout,config).then(graph=>{graphById[chart.id]=graph;installVerticalControl(chart,graph);installXLink(graph);});
})).then(()=>{
  const resize=()=>Object.values(graphById).forEach(graph=>Plotly.Plots.resize(graph));
  if(window.ResizeObserver) new ResizeObserver(resize).observe(document.body);
  else window.addEventListener('resize',resize);
  document.getElementById('quick-export').addEventListener('click',downloadQuickExport);
});
</script></body></html>""".replace("__PLOTLY_JS__", get_plotlyjs()).replace(
        "__CARDS__", cards
    ).replace("__PAYLOAD__", payload_json).replace(
        "__EXPORT_LABEL__", "导出当前 10 个轮次高清截图" if cycles_quick_export else "导出当前范围高清截图"
    ).replace("__EXPORT_CYCLES__", "true" if cycles_quick_export else "false").replace(
        "__EXPORT_WIDTH__", str(QUICK_EXPORT_WIDTH_PX)
    ).replace("__EXPORT_HEIGHT__", str(QUICK_EXPORT_HEIGHT_PX))
