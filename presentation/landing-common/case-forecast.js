(() => {
  const root=document.querySelector('[data-case-forecast]'); if(!root) return;
  const data=JSON.parse(root.querySelector('[data-case-data]').textContent);
  const city=root.querySelector('[data-case-city]'),cat=root.querySelector('[data-case-category]');
  const chart=root.querySelector('[data-case-chart]'),error=root.querySelector('[data-case-error]');
  const fmt=n=>n.toLocaleString('ru-RU',{maximumFractionDigits:2});
  const months={'2024-04':'Апрель','2024-05':'Май','2024-06':'Июнь'};
  function render(){
    const row=data.find(x=>x.municipality===city.value && x.category===cat.value); if(!row) return;
    const points=row.points,xs=[95,370,645],max=Math.max(...points.flatMap(p=>[p.actual,p.forecast]))*1.15;
    const y=n=>200-n/max*170;
    chart.setAttribute('aria-label',row.municipality+' · '+row.category+' · факт и прогноз апрель–июнь2024');
    chart.innerHTML='<line x1="60" y1="200" x2="670" y2="200" stroke="#756d87"/>'+[0,max/2,max].map(n=>'<text x="53" y="'+y(n)+'" text-anchor="end" fill="#beb6cc" font-size="12">'+fmt(n)+'</text>').join('')+['actual','forecast'].map((key,i)=>'<polyline fill="none" stroke="'+['#8bdfda','#f3bd74'][i]+'" stroke-width="3" points="'+points.map((p,j)=>xs[j]+','+y(p[key])).join(' ')+'"/>'+points.map((p,j)=>'<circle cx="'+xs[j]+'" cy="'+y(p[key])+'" r="4" fill="'+['#8bdfda','#f3bd74'][i]+'"/>').join('')).join('')+points.map((p,j)=>'<text x="'+xs[j]+'" y="226" text-anchor="middle" fill="#beb6cc" font-size="13">'+months[p.target]+'</text>').join('');
    const bound=Math.max(5,...points.map(p=>Math.abs(p.residual_percent)))*1.3,ey=n=>70-n/bound*55;
    error.innerHTML='<line x1="60" y1="70" x2="680" y2="70" stroke="#756d87"/>'+points.map((p,j)=>'<rect x="'+(xs[j]-30)+'" y="'+Math.min(70,ey(p.residual_percent))+'" width="60" height="'+Math.abs(ey(p.residual_percent)-70)+'" fill="'+(p.residual_percent<0?'#bd9cdb':'#8bdfda')+'"/><text x="'+xs[j]+'" y="'+(p.residual_percent<0?ey(p.residual_percent)+16:ey(p.residual_percent)-8)+'" text-anchor="middle" fill="#ded7e9" font-size="13">'+fmt(p.residual_percent)+'%</text><text x="'+xs[j]+'" y="151" text-anchor="middle" fill="#beb6cc" font-size="13">'+months[p.target]+'</text>').join('');
    root.querySelector('[data-case-table]').innerHTML='<table><thead><tr><th scope="col">Месяц</th><th scope="col">Факт</th><th scope="col">Прогноз</th><th scope="col">Отклонение,%</th></tr></thead><tbody>'+points.map(p=>'<tr><td>'+months[p.target]+'</td><td>'+fmt(p.actual)+'</td><td>'+fmt(p.forecast)+'</td><td>'+fmt(p.residual_percent)+'</td></tr>').join('')+'</tbody></table>';
  }
  city.addEventListener('change',render);cat.addEventListener('change',render);render();
})();
