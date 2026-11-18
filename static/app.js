/* AttendanceSmart frontend — browser interface for Flask JSON endpoints. */
const $ = (id) => document.getElementById(id);
const state = {
  view: 'dashboard', date: localDate(), search: '', filter: 'All',
  overview: null, students: [], attendance: null, reports: null, schedule: null
};
let toastTimer;

function localDate() {
  const d = new Date();
  const f = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${f(d.getMonth() + 1)}-${f(d.getDate())}`;
}
function prettyDate(iso, opts={ weekday:'long',day:'numeric',month:'long',year:'numeric' }) {
  return new Date(`${iso}T12:00:00`).toLocaleDateString('en-US', opts);
}
function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));
}
function icon(name, cls='') {
  return `<svg class="${cls}" aria-hidden="true"><use href="#ico-${name}"></use></svg>`;
}
function toast(message, error=false) {
  const el = $('toast');
  clearTimeout(toastTimer);
  el.textContent = message;
  el.classList.toggle('error', error);
  el.classList.add('visible');
  toastTimer = setTimeout(() => el.classList.remove('visible'), 3800);
}
async function api(path, options={}) {
  let response;
  try {
    response = await fetch(path, { ...options, headers: { 'Content-Type':'application/json', ...(options.headers||{}) } });
  } catch {
    throw new Error('Cannot connect to Flask. Run: py app.py');
  }
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status}).`);
  return result;
}
function failed(error) { console.error(error); toast(error.message || 'Unexpected error.', true); }
function studentIcon() { return `<span class="student-avatar">${icon('graduate')}</span>`; }
function statusBadge(status) {
  const s = status || 'Unmarked';
  return `<span class="status-badge status-${s.toLowerCase()}">${esc(s === 'Unmarked' ? 'Not marked' : s)}</span>`;
}
function emptyRow(columns, message, note='') {
  return `<tr><td colspan="${columns}" class="empty-state"><strong>${esc(message)}</strong>${note ? `<p>${esc(note)}</p>` : ''}</td></tr>`;
}
function matches(row) {
  const q = state.search.trim().toLowerCase();
  return !q || [row.name,row.student_no,row.section].some(x => String(x ?? '').toLowerCase().includes(q));
}
function renderInsights(el, insights) {
  const typeIcon = { danger:'alert', warning:'clock', success:'check-circle', info:'info' };
  $(el).innerHTML = (insights || []).map(item => `
    <div class="insight ${esc(item.type)}">
      ${icon(typeIcon[item.type] || 'info','insight-icon')}
      <div><div class="insight-title">${esc(item.title)}</div><div class="insight-detail">${esc(item.detail)}</div>
      ${(item.names || []).length ? `<div class="insight-names">${esc(item.names.join(', '))}</div>` : ''}</div>
    </div>`).join('') || '<div class="empty-inline">No insights yet.</div>';
}
function renderChart(week) {
  if (!week || week.every(d => d.rate === null)) {
    $('week-chart').innerHTML = '<div class="empty-inline">No marked attendance this week yet.<br>Record a class to start the chart.</div>';
    return;
  }
  $('week-chart').innerHTML = `<div class="chart-layout">
    <div class="chart-axis"><span>100%</span><span>75%</span><span>50%</span><span>25%</span><span>0%</span></div>
    <div class="chart-plot"><div class="chart-grid"></div><div class="chart-bars">
      ${week.map(d => {
        const noData = d.rate === null;
        const rate = noData ? 0 : d.rate;
        return `<div class="chart-col" title="${esc(prettyDate(d.date))}: ${noData ? 'No records' : `${rate}% attendance`}">
          <div class="chart-column-inner" style="--bar-height: ${rate}%">
            <span class="chart-value">${noData ? '—' : `${rate}%`}</span>
            <div class="chart-bar ${noData ? 'no-data' : ''}"></div>
          </div><span class="chart-day">${esc(d.label)}</span></div>`;
      }).join('')}
    </div></div></div>`;
}
function renderDashboard() {
  const x = state.overview;
  if (!x) return;
  const s = x.summary;
  $('metric-present').textContent = s.present;
  $('metric-absent').textContent = s.absent;
  $('metric-late').textContent = s.late;
  $('metric-rate').textContent = s.attendance_rate === null ? '—' : `${s.attendance_rate}%`;
  $('metric-present-caption').textContent = `${s.total} enrolled students`;
  $('metric-absent-caption').textContent = `${s.unmarked} not yet marked`;
  $('metric-rate-caption').textContent = s.attendance_rate === null ? 'No counted records yet' : 'Present + Late / counted records';
  renderChart(x.week);
  renderInsights('dashboard-insights', x.insights);
  const all = x.students;
  const visible = all.filter(matches).filter(r => state.filter === 'All' || (r.status || 'Unmarked') === state.filter);
  $('dashboard-student-count').textContent = `${all.length} enrolled`;
  $('dashboard-footnote').textContent = `${visible.length} of ${all.length} students shown · ${s.excused} excused · ${s.unmarked} unmarked`;
  $('dashboard-rows').innerHTML = visible.length ? visible.map(row => `<tr>
    <td><div class="student-cell">${studentIcon()}<div><span class="student-name">${esc(row.name)}</span><span class="student-sub">${esc(row.student_no)}</span></div></div></td>
    <td>${esc(row.section)}</td>
    <td>${row.checkin_time ? esc(to12Hour(row.checkin_time)) : '—'}</td>
    <td>${statusBadge(row.status)}</td>
  </tr>`).join('') : emptyRow(4, all.length ? 'No matching students.' : 'No students added yet.', all.length ? 'Try another filter or search.' : 'Open Students to add your first student.');
}
function to12Hour(t) {
  const [hh,mm] = t.split(':').map(Number);
  return `${hh % 12 || 12}:${String(mm).padStart(2, '0')} ${hh >= 12 ? 'PM' : 'AM'}`;
}
function renderStudents() {
  const all = state.students;
  const list = all.filter(matches);
  $('student-total-badge').textContent = `${all.length} student${all.length !== 1 ? 's' : ''}`;
  $('roster-count').textContent = `${list.length} shown`;
  $('student-rows').innerHTML = list.length ? list.map(s => `<tr>
    <td>${esc(s.student_no)}</td>
    <td><div class="student-cell">${studentIcon()}<span class="student-name">${esc(s.name)}</span></div></td>
    <td>${esc(s.section)}</td>
    <td class="actions-cell"><button class="icon-action" type="button" data-edit="${s.id}" title="Edit ${esc(s.name)}" aria-label="Edit ${esc(s.name)}">${icon('edit')}</button><button class="icon-action danger" type="button" data-delete="${s.id}" title="Delete ${esc(s.name)}" aria-label="Delete ${esc(s.name)}">${icon('trash')}</button></td>
  </tr>`).join('') : emptyRow(4, all.length ? 'No matching students.' : 'Your classroom is empty.', all.length ? '' : 'Use the form on the left to add a student.');
}
function clearStudentForm() {
  $('student-form').reset();
  $('edit-student-id').value='';
  $('student-form-title').textContent='Add a student';
  $('save-student').innerHTML = `${icon('plus')} Add student`;
  $('cancel-edit').classList.add('hidden');
}
function beginEditStudent(id) {
  const s = state.students.find(x => x.id === Number(id));
  if (!s) return;
  $('student-name').value = s.name;
  $('student-section').value = s.section;
  $('student-number').value = s.student_no;
  $('edit-student-id').value = s.id;
  $('student-form-title').textContent='Edit student';
  $('save-student').innerHTML = `${icon('save')} Save changes`;
  $('cancel-edit').classList.remove('hidden');
  $('student-name').focus();
}
function renderAttendance() {
  const data = state.attendance;
  if (!data) return;
  ['present','late','absent','excused','unmarked'].forEach(key => $('count-'+key).textContent = data.summary[key]);
  const all = data.students;
  const filtered = all.filter(matches);
  $('attendance-rows').innerHTML = filtered.length ? filtered.map(s => `<tr data-attendance-id="${s.id}">
    <td><div class="student-cell">${studentIcon()}<div><span class="student-name">${esc(s.name)}</span><span class="student-sub">${esc(s.student_no)}</span></div></div></td>
    <td>${esc(s.section)}</td>
    <td><select aria-label="Attendance status for ${esc(s.name)}" class="small-select attendance-status">
      ${['Unmarked','Present','Late','Absent','Excused'].map(status => `<option value="${status}" ${status === (s.status || 'Unmarked') ? 'selected':''}>${status}</option>`).join('')}
    </select></td>
    <td><input aria-label="Check-in time for ${esc(s.name)}" class="time-input attendance-time" type="time" value="${esc(s.checkin_time || '')}" ${(s.status === 'Absent' || s.status === 'Excused') ? 'disabled' : ''}></td>
    <td><button type="button" class="small-save" data-save-attendance="${s.id}">Save</button></td>
  </tr>`).join('') : emptyRow(5, all.length ? 'No matching students.' : 'No students to mark.', all.length ? '' : 'Add students in the Students section first.');
}
function renderSchedule() {
  if (!state.schedule) return;
  $('grace-minutes').value = state.schedule.grace_minutes;
  $('schedule-days').innerHTML = state.schedule.days.map(item => `<div class="schedule-day" data-weekday="${item.weekday}">
    <div class="day-name">${esc(item.name)}</div>
    <label><input type="checkbox" class="schedule-enabled" ${item.enabled ? 'checked':''}> Class day</label>
    <input type="time" class="schedule-time" value="${esc(item.start_time)}" ${item.enabled ? '' : 'disabled'} aria-label="${esc(item.name)} start time" required>
  </div>`).join('');
}
function renderReports() {
  const x = state.reports;
  if (!x) return;
  $('report-range').textContent = `${prettyDate(x.start_date,{month:'short',day:'numeric'})} – ${prettyDate(x.end_date,{month:'short',day:'numeric'})}`;
  renderInsights('report-insights', x.insights);
  const list = x.students.filter(matches);
  $('report-rows').innerHTML = list.length ? list.map(s => `<tr>
    <td><div class="student-cell">${studentIcon()}<span class="student-name">${esc(s.name)}</span></div></td>
    <td>${esc(s.section)}</td><td>${s.present}</td><td>${s.late}</td><td>${s.absent}</td><td>${s.excused}</td>
    <td><strong>${s.rate === null ? '—' : `${s.rate}%`}</strong></td>
  </tr>`).join('') : emptyRow(7, x.students.length ? 'No matching students.' : 'Nothing to report yet.', x.students.length ? '' : 'Add students and attendance records to create reports.');
}
async function refresh() {
  switch (state.view) {
    case 'dashboard':
      state.overview = await api(`/api/overview?date=${encodeURIComponent(state.date)}`);
      renderDashboard(); break;
    case 'students':
      state.students = (await api('/api/students')).students;
      renderStudents(); break;
    case 'attendance':
      state.attendance = await api(`/api/attendance?date=${encodeURIComponent(state.date)}`);
      renderAttendance(); break;
    case 'schedules':
      state.schedule = await api('/api/schedule');
      renderSchedule(); break;
    case 'reports':
      state.reports = await api(`/api/reports?date=${encodeURIComponent(state.date)}`);
      renderReports(); break;
  }
}
const PAGE_META = {
  dashboard:['Attendance Monitoring','Student Attendance Monitoring System Using Arrays and Sets'],
  students:['Students','Keep your classroom roster organized'],
  attendance:['Attendance','Record daily check-ins and attendance statuses'],
  schedules:['Schedules','Manage class times and late-arrival rules'],
  reports:['Reports','Review attendance trends and intelligent insights'],
  settings:['Settings','Local data and classroom preferences']
};
function changeView(name) {
  if (!PAGE_META[name]) return;
  state.view = name;
  $('page-title').textContent = PAGE_META[name][0];
  $('page-subtitle').textContent = PAGE_META[name][1];
  document.querySelectorAll('.nav-item').forEach(x => x.classList.toggle('active',x.dataset.nav === name));
  document.querySelectorAll('.view').forEach(x => x.classList.toggle('active',x.id === 'view-'+name));
  $('sidebar').classList.remove('open');
  $('mobile-overlay').classList.remove('show');
  $('mobile-overlay').hidden = true;
  window.scrollTo({top:0,behavior:'instant'});
  refresh().catch(failed);
}
function syncDate(date) {
  state.date = date;
  $('dash-date').value=date;
  $('attendance-date').value=date;
  $('header-date').textContent=prettyDate(date);
  refresh().catch(failed);
}
// Navigation and global filters
for (const link of document.querySelectorAll('[data-nav]')) {
  link.addEventListener('click', () => changeView(link.dataset.nav));
}
for (const link of document.querySelectorAll('[data-go]')) {
  link.addEventListener('click', () => changeView(link.dataset.go));
}
$('global-search').addEventListener('input', e => {
  state.search=e.target.value;
  switch (state.view) {
    case 'dashboard': renderDashboard(); break;
    case 'students': renderStudents(); break;
    case 'attendance': renderAttendance(); break;
    case 'reports': renderReports(); break;
  }
});
for (const dateInput of [$('dash-date'),$('attendance-date')]) {
  dateInput.addEventListener('change', e => {
    if (e.target.value) syncDate(e.target.value);
  });
}
$('dashboard-filters').addEventListener('click', e => {
  const button=e.target.closest('[data-filter]');
  if (!button) return;
  state.filter=button.dataset.filter;
  $('dashboard-filters').querySelectorAll('button').forEach(x => x.classList.toggle('selected',x === button));
  renderDashboard();
});
$('menu-toggle').addEventListener('click', () => {
  $('sidebar').classList.toggle('open');
  const open=$('sidebar').classList.contains('open');
  $('mobile-overlay').hidden=!open;
  $('mobile-overlay').classList.toggle('show',open);
});
$('mobile-overlay').addEventListener('click', () => { $('sidebar').classList.remove('open'); $('mobile-overlay').classList.remove('show'); $('mobile-overlay').hidden=true; });

// Roster create, edit, and delete
$('student-form').addEventListener('submit',async (e)=>{
  e.preventDefault();
  const id=$('edit-student-id').value;
  const input={name:$('student-name').value,section:$('student-section').value,student_no:$('student-number').value};
  const button=$('save-student');
  button.disabled=true;
  try {
    await api(id ? `/api/students/${id}` : '/api/students', {
      method:id ? 'PATCH':'POST', body:JSON.stringify(input)
    });
    toast(id ? 'Student updated successfully.' : 'Student added successfully.');
    clearStudentForm(); await refresh();
  } catch(err) { failed(err); }
  finally { button.disabled=false; }
});
$('cancel-edit').addEventListener('click',clearStudentForm);
$('student-rows').addEventListener('click',async (e)=>{
  const edit=e.target.closest('[data-edit]');
  if (edit) { beginEditStudent(edit.dataset.edit); return; }
  const del=e.target.closest('[data-delete]');
  if (!del) return;
  const student=state.students.find(s=>s.id===Number(del.dataset.delete));
  if (!student || !confirm(`Delete ${student.name} and all their attendance history?`)) return;
  del.disabled=true;
  try {
    await api(`/api/students/${student.id}`,{method:'DELETE'});
    if ($('edit-student-id').value===String(student.id)) clearStudentForm();
    toast('Student deleted.'); await refresh();
  } catch(err) { failed(err); del.disabled=false; }
});

// Save each attendance row. A single date+student pair can have only one status.
$('attendance-rows').addEventListener('change',e=>{
  if (!e.target.classList.contains('attendance-status')) return;
  const row=e.target.closest('[data-attendance-id]');
  const time=row.querySelector('.attendance-time');
  time.disabled=['Absent','Excused','Unmarked'].includes(e.target.value);
  if (time.disabled) time.value='';
});
$('attendance-rows').addEventListener('click',async e=>{
  const button=e.target.closest('[data-save-attendance]');
  if (!button) return;
  const row=button.closest('[data-attendance-id]');
  const id=Number(row.dataset.attendanceId);
  const status=row.querySelector('.attendance-status').value;
  const checkin_time=row.querySelector('.attendance-time').value;
  button.disabled=true;
  try {
    const result=await api(`/api/attendance/${id}`,{
      method:'PUT',body:JSON.stringify({date:state.date,status,checkin_time})
    });
    toast(result.status === 'Late' && status === 'Present' ? 'Attendance saved as Late based on the schedule.' : 'Attendance saved.');
    await refresh();
  } catch(err) { failed(err); button.disabled=false; }
});

// Schedule forms
$('schedule-days').addEventListener('change', e => {
  if (!e.target.classList.contains('schedule-enabled')) return;
  const row=e.target.closest('.schedule-day');
  row.querySelector('.schedule-time').disabled=!e.target.checked;
});
$('schedule-form').addEventListener('submit',async e => {
  e.preventDefault();
  const days=Array.from(document.querySelectorAll('.schedule-day')).map(row=>({
    weekday:Number(row.dataset.weekday),
    enabled:row.querySelector('.schedule-enabled').checked,
    start_time:row.querySelector('.schedule-time').value
  }));
  const payload={days,grace_minutes:Number($('grace-minutes').value)};
  const button=e.target.querySelector('[type=submit]'); button.disabled=true;
  try { await api('/api/schedule',{method:'PUT',body:JSON.stringify(payload)}); toast('Class schedule updated.'); await refresh(); }
  catch(err) { failed(err); } finally {button.disabled=false;}
});

// Optional demonstration data, not loaded automatically.
$('load-demo').addEventListener('click',async ()=>{
  if (!confirm('Add 10 sample students and 10 school days of attendance? Only works with an empty roster.')) return;
  $('load-demo').disabled=true;
  try { const result=await api('/api/demo',{method:'POST',body:'{}'}); toast(result.message); syncDate(localDate()); changeView('dashboard'); }
  catch(err) { failed(err); } finally {$('load-demo').disabled=false;}
});
$('clear-data').addEventListener('click',async ()=>{
  if (!confirm('This permanently removes ALL students and attendance records. Continue?')) return;
  if (!confirm('Final confirmation: permanently clear your classroom data?')) return;
  $('clear-data').disabled=true;
  try { await api('/api/reset',{method:'POST',body:JSON.stringify({confirm:'DELETE ALL'})}); toast('All student records have been cleared.'); changeView('dashboard'); }
  catch(err) { failed(err); } finally {$('clear-data').disabled=false;}
});

// Initialize once after the DOM has loaded (script is deferred).
syncDate(state.date);
