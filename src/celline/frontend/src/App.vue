<template>
  <div id="app">
    <!-- Header -->
    <header class="header">
      <div class="container">
        <h1>🧬 Celline Interactive</h1>
        <nav>
          <button 
            @click="activeTab = 'overview'" 
            :class="{ active: activeTab === 'overview' }"
            class="nav-btn"
          >
            Overview
          </button>
          <button 
            @click="activeTab = 'samples'" 
            :class="{ active: activeTab === 'samples' }"
            class="nav-btn"
          >
            Samples
          </button>
          <button 
            @click="activeTab = 'analysis'" 
            :class="{ active: activeTab === 'analysis' }"
            class="nav-btn"
          >
            Analysis
          </button>
          <button 
            @click="showLogs = !showLogs" 
            :class="{ active: showLogs }"
            class="nav-btn logs-btn"
          >
            📋 Logs
          </button>
        </nav>
      </div>
    </header>

    <!-- Main Content -->
    <main class="main-content">
      <div class="container">
        <!-- Overview Tab -->
        <div v-if="activeTab === 'overview'" class="tab-content">
          <div v-if="error" class="error-message">
            {{ error }}
            <button @click="loadProjectData" class="retry-btn">Retry</button>
          </div>
          
          <div v-if="loading" class="loading-message">
            Loading project data...
          </div>
          
          <div v-else class="welcome-section">
            <h2>Welcome to Celline</h2>
            <p v-if="projectInfo">Project: {{ projectInfo.name }}</p>
            <p v-else>Manage your single-cell RNA-seq analysis projects with ease.</p>
          </div>
          
          <div class="stats-grid">
            <div class="stat-card">
              <h3>{{ samples.length }}</h3>
              <p>Total Samples</p>
            </div>
            <div class="stat-card">
              <h3>{{ samples.filter(s => s.status === 'completed').length }}</h3>
              <p>Processed</p>
            </div>
            <div class="stat-card">
              <h3>{{ samples.filter(s => s.status === 'pending').length }}</h3>
              <p>Pending</p>
            </div>
          </div>
        </div>

        <!-- Samples Tab -->
        <div v-if="activeTab === 'samples'" class="tab-content">
          <div class="samples-header">
            <h2>Sample Management</h2>
            <div class="sample-actions">
              <input 
                v-model="newSampleId" 
                placeholder="Enter sample ID(s) (e.g., GSE123456, GSM123457)"
                class="sample-input"
                @keyup.enter="addSample"
                :disabled="loading"
              >
              <button @click="addSample" class="add-btn" :disabled="!newSampleId || loading">
                {{ loading ? 'Adding...' : 'Add Sample' }}
              </button>
            </div>
          </div>

          <div class="samples-list">
            <div v-if="samples.length === 0" class="empty-state">
              <p>No samples added yet. Start by adding a sample ID above.</p>
            </div>
            
            <div v-for="sample in samples" :key="sample.id" class="sample-card">
              <div class="sample-info">
                <h3>{{ sample.id }}</h3>
                <p v-if="sample.title && sample.title !== sample.id">{{ sample.title }}</p>
                <p v-if="sample.summary" class="sample-summary">{{ sample.summary }}</p>
                <div class="sample-metadata">
                  <span v-if="sample.species" class="metadata-tag">{{ sample.species }}</span>
                  <span class="metadata-tag">Added: {{ formatDate(sample.addedAt) }}</span>
                </div>
                <span :class="['status', getSampleStatus(sample).split(' ')[0]]">{{ getSampleStatus(sample) }}</span>
              </div>
              <div class="sample-actions">
                <button 
                  @click="downloadSample(sample.id)" 
                  class="action-btn download-btn"
                  :disabled="loading"
                  v-if="sample.status === 'pending'"
                >
                  Download
                </button>
                <button 
                  @click="countSample(sample.id)" 
                  class="action-btn count-btn"
                  :disabled="loading"
                  v-if="sample.status === 'downloaded'"
                >
                  Count
                </button>
                <button 
                  @click="preprocessSample(sample.id)" 
                  class="action-btn preprocess-btn"
                  :disabled="loading"
                  v-if="sample.status === 'processing'"
                >
                  QC/Preprocess
                </button>
                <button @click="removeSample(sample.id)" class="remove-btn" :disabled="loading">
                  Remove
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Analysis Tab -->
        <div v-if="activeTab === 'analysis'" class="tab-content">
          <h2>Analysis Tools</h2>
          <div class="analysis-grid">
            <div class="analysis-card">
              <h3>Preprocessing</h3>
              <p>Quality control and normalization</p>
              <button class="analysis-btn" :disabled="samples.length === 0">
                Run Preprocessing
              </button>
            </div>
            <div class="analysis-card">
              <h3>Integration</h3>
              <p>Batch correction and integration</p>
              <button class="analysis-btn" :disabled="samples.length === 0">
                Run Integration
              </button>
            </div>
            <div class="analysis-card">
              <h3>Cell Type Prediction</h3>
              <p>Automated cell type annotation</p>
              <button class="analysis-btn" :disabled="samples.length === 0">
                Predict Cell Types
              </button>
            </div>
          </div>
        </div>
      </div>
    </main>

    <!-- Log Window -->
    <div v-if="showLogs" class="log-window">
      <div class="log-header">
        <h3>📋 Operation Logs</h3>
        <div class="log-controls">
          <button @click="clearLogs" class="clear-btn">Clear</button>
          <button @click="showLogs = false" class="close-btn">✕</button>
        </div>
      </div>
      <div class="log-content">
        <div v-if="logs.length === 0" class="log-empty">
          No logs yet. Start by adding a sample to see operation logs.
        </div>
        <div v-for="log in logs" :key="log.id" :class="['log-entry', log.type]">
          <span class="log-timestamp">{{ log.timestamp }}</span>
          <span class="log-message">{{ log.message }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { defineComponent, ref, reactive, onMounted } from "vue";
import axios from 'axios';

const API_BASE = 'http://localhost:8000/api';

export default defineComponent({
  name: 'CellineApp',
  setup() {
    const activeTab = ref('overview');
    const newSampleId = ref('');
    const samples = reactive([]);
    const projectInfo = ref(null);
    const loading = ref(false);
    const error = ref('');
    const jobs = reactive({});
    const logs = reactive([]);
    const showLogs = ref(false);

    // Load project data on mount
    onMounted(async () => {
      await loadProjectData();
    });

    // Log functionality
    const addToLog = (message, type = 'info') => {
      const timestamp = new Date().toLocaleTimeString();
      logs.push({
        id: Date.now(),
        timestamp,
        message,
        type
      });
      // Keep only last 100 log entries
      if (logs.length > 100) {
        logs.splice(0, logs.length - 100);
      }
    };

    const clearLogs = () => {
      logs.splice(0, logs.length);
    };

    const loadProjectData = async () => {
      try {
        loading.value = true;
        error.value = '';
        
        const response = await axios.get(`${API_BASE}/project`);
        projectInfo.value = response.data;
        
        // Clear and update samples
        samples.splice(0, samples.length);
        response.data.samples.forEach(sample => {
          samples.push({
            ...sample,
            addedAt: new Date(sample.addedAt)
          });
        });
        
      } catch (err) {
        if (err.code === 'ECONNREFUSED' || err.message?.includes('Network Error')) {
          error.value = 'Cannot connect to Celline API server. Please make sure the server is running on http://localhost:8000';
        } else {
          error.value = `Failed to load project: ${err.response?.data?.detail || err.message}`;
        }
        console.error('Error loading project:', err);
      } finally {
        loading.value = false;
      }
    };

    const addSample = async () => {
      if (!newSampleId.value.trim()) return;
      
      try {
        loading.value = true;
        error.value = '';
        
        const sampleIds = newSampleId.value.split(',').map(id => id.trim()).filter(id => id);
        
        // Add samples with 'adding' status immediately to show loading
        sampleIds.forEach(sampleId => {
          const existingSample = samples.find(s => s.id === sampleId);
          if (!existingSample) {
            samples.push({
              id: sampleId,
              title: sampleId,
              status: 'adding',
              addedAt: new Date()
            });
          }
        });
        
        addToLog(`🔄 Starting to add ${sampleIds.length} samples: ${sampleIds.join(', ')}`);
        console.log(`[Frontend] Sending add request for samples: ${sampleIds}`);
        
        const response = await axios.post(`${API_BASE}/samples/add`, {
          sample_ids: sampleIds
        });
        
        console.log(`[Frontend] Add response:`, response.data);
        
        // Track job
        const jobId = response.data.job_id;
        jobs[jobId] = {
          id: jobId,
          type: 'add_samples',
          samples: sampleIds,
          status: 'pending',
          message: 'Adding samples...'
        };
        
        addToLog(`📋 Job ${jobId} started for adding samples`);
        console.log(`[Frontend] Starting to poll job ${jobId}`);
        
        // Poll job status
        pollJobStatus(jobId);
        
        newSampleId.value = '';
        
      } catch (err) {
        let errorMessage = '';
        if (err.code === 'ECONNREFUSED' || err.message?.includes('Network Error')) {
          errorMessage = 'Cannot connect to Celline API server. Please make sure the server is running on http://localhost:8000';
        } else {
          errorMessage = `Failed to add sample: ${err.response?.data?.detail || err.message}`;
        }
        error.value = errorMessage;
        addToLog(`❌ ERROR: ${errorMessage}`, 'error');
        
        // Remove pending samples on error
        const sampleIds = newSampleId.value.split(',').map(id => id.trim()).filter(id => id);
        sampleIds.forEach(sampleId => {
          const index = samples.findIndex(s => s.id === sampleId && s.status === 'adding');
          if (index > -1) {
            samples.splice(index, 1);
          }
        });
        
        console.error('Error adding sample:', err);
      } finally {
        loading.value = false;
      }
    };

    const runSampleAction = async (sampleId, action) => {
      try {
        loading.value = true;
        error.value = '';
        
        // Update sample status to show loading
        const sample = samples.find(s => s.id === sampleId);
        if (sample) {
          sample.status = `${action}ing`;
        }
        
        addToLog(`🔄 Starting ${action} for sample ${sampleId}`);
        
        const response = await axios.post(`${API_BASE}/samples/${sampleId}/${action}`);
        
        // Track job
        const jobId = response.data.job_id;
        jobs[jobId] = {
          id: jobId,
          type: action,
          sample: sampleId,
          status: 'pending'
        };
        
        addToLog(`📋 Job ${jobId} started for ${action} on ${sampleId}`);
        
        // Poll job status
        pollJobStatus(jobId);
        
      } catch (err) {
        const errorMessage = `Failed to ${action} sample: ${err.response?.data?.detail || err.message}`;
        error.value = errorMessage;
        addToLog(`❌ ERROR: ${errorMessage}`, 'error');
        
        // Reset sample status on error
        const sample = samples.find(s => s.id === sampleId);
        if (sample) {
          sample.status = 'pending';
        }
        
        console.error(`Error ${action}ing sample:`, err);
      } finally {
        loading.value = false;
      }
    };

    const downloadSample = (sampleId) => runSampleAction(sampleId, 'download');
    const countSample = (sampleId) => runSampleAction(sampleId, 'count');
    const preprocessSample = (sampleId) => runSampleAction(sampleId, 'preprocess');

    const pollJobStatus = async (jobId) => {
      try {
        console.log(`[Frontend] Polling job status for ${jobId}`);
        const response = await axios.get(`${API_BASE}/jobs/${jobId}`);
        const job = response.data;
        console.log(`[Frontend] Job ${jobId} status: ${job.status} - ${job.message}`);
        
        jobs[jobId].status = job.status;
        jobs[jobId].message = job.message;
        jobs[jobId].progress = job.progress;
        
        // Log job progress updates
        if (job.status === 'running') {
          addToLog(`🔄 Job ${jobId}: ${job.message}`, 'info');
        } else if (job.status === 'completed') {
          addToLog(`✅ Job ${jobId}: ${job.message}`, 'success');
          
          // Update sample status from loading to pending immediately
          if (jobs[jobId].type === 'add_samples' && jobs[jobId].samples) {
            jobs[jobId].samples.forEach(sampleId => {
              const sample = samples.find(s => s.id === sampleId);
              if (sample && sample.status === 'adding') {
                sample.status = 'pending';
              }
            });
          } else if (jobs[jobId].sample) {
            const sample = samples.find(s => s.id === jobs[jobId].sample);
            if (sample) {
              // Update to next logical status based on operation
              if (jobs[jobId].type === 'download') {
                sample.status = 'downloaded';
              } else if (jobs[jobId].type === 'count') {
                sample.status = 'processing';
              } else if (jobs[jobId].type === 'preprocess') {
                sample.status = 'completed';
              } else {
                sample.status = 'pending';
              }
            }
          }
          
          // Reload project data to get the latest information from the server
          setTimeout(async () => {
            await loadProjectData();
            addToLog(`🔄 Refreshed project data after job completion`, 'info');
          }, 1000);
        } else if (job.status === 'failed') {
          addToLog(`❌ Job ${jobId}: ${job.message}`, 'error');
          
          // Remove failed samples from the list if they were in 'adding' state
          if (jobs[jobId].type === 'add_samples' && jobs[jobId].samples) {
            jobs[jobId].samples.forEach(sampleId => {
              const sampleIndex = samples.findIndex(s => s.id === sampleId && s.status === 'adding');
              if (sampleIndex > -1) {
                samples.splice(sampleIndex, 1);
              }
            });
          }
        }
        
        if (job.status === 'running' || job.status === 'pending') {
          // Continue polling
          setTimeout(() => pollJobStatus(jobId), 2000);
        }
        
      } catch (err) {
        addToLog(`❌ Error polling job ${jobId}: ${err.message}`, 'error');
        console.error('Error polling job status:', err);
      }
    };

    const removeSample = (sampleId) => {
      const index = samples.findIndex(s => s.id === sampleId);
      if (index > -1) {
        samples.splice(index, 1);
        // TODO: Implement actual sample removal API
        console.log('Removing sample:', sampleId);
      }
    };

    const getJobsForSample = (sampleId) => {
      return Object.values(jobs).filter(job => job.sample === sampleId);
    };

    const getSampleStatus = (sample) => {
      const sampleJobs = getJobsForSample(sample.id);
      const runningJob = sampleJobs.find(job => job.status === 'running');
      
      if (runningJob) {
        return `${runningJob.type} (${runningJob.status})`;
      }
      
      return sample.status;
    };

    const formatDate = (date) => {
      if (!date) return '';
      const d = new Date(date);
      return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    };

    return {
      activeTab,
      newSampleId,
      samples,
      projectInfo,
      loading,
      error,
      jobs,
      logs,
      showLogs,
      addSample,
      removeSample,
      downloadSample,
      countSample,
      preprocessSample,
      getJobsForSample,
      getSampleStatus,
      loadProjectData,
      addToLog,
      clearLogs,
      formatDate
    };
  },
});
</script>

<style scoped>
/* Global Styles */
* {
  box-sizing: border-box;
}

#app {
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  background-color: #f8fafc;
  min-height: 100vh;
}

.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 1rem;
}

/* Header */
.header {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  padding: 1rem 0;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
}

.header .container {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header h1 {
  margin: 0;
  font-size: 1.8rem;
  font-weight: 600;
}

nav {
  display: flex;
  gap: 1rem;
}

.nav-btn {
  background: rgba(255, 255, 255, 0.2);
  color: white;
  border: none;
  padding: 0.5rem 1rem;
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.3s ease;
}

.nav-btn:hover {
  background: rgba(255, 255, 255, 0.3);
}

.nav-btn.active {
  background: white;
  color: #667eea;
}

/* Main Content */
.main-content {
  padding: 2rem 0;
}

.tab-content {
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Overview Tab */
.welcome-section {
  text-align: center;
  margin-bottom: 3rem;
}

.welcome-section h2 {
  font-size: 2.5rem;
  margin-bottom: 1rem;
  color: #2d3748;
}

.welcome-section p {
  font-size: 1.2rem;
  color: #718096;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1.5rem;
  margin-bottom: 2rem;
}

.stat-card {
  background: white;
  padding: 2rem;
  border-radius: 12px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
  text-align: center;
  border: 1px solid #e2e8f0;
}

.stat-card h3 {
  font-size: 2.5rem;
  margin: 0 0 0.5rem 0;
  color: #667eea;
  font-weight: 700;
}

.stat-card p {
  margin: 0;
  color: #718096;
  font-weight: 500;
}

/* Samples Tab */
.samples-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2rem;
  flex-wrap: wrap;
  gap: 1rem;
}

.samples-header h2 {
  margin: 0;
  color: #2d3748;
}

.sample-actions {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.sample-input {
  padding: 0.75rem 1rem;
  border: 2px solid #e2e8f0;
  border-radius: 8px;
  font-size: 1rem;
  transition: border-color 0.3s ease;
  min-width: 250px;
}

.sample-input:focus {
  outline: none;
  border-color: #667eea;
}

.add-btn {
  background: #667eea;
  color: white;
  border: none;
  padding: 0.75rem 1.5rem;
  border-radius: 8px;
  cursor: pointer;
  font-weight: 500;
  transition: background-color 0.3s ease;
}

.add-btn:hover:not(:disabled) {
  background: #5a67d8;
}

.add-btn:disabled {
  background: #cbd5e0;
  cursor: not-allowed;
}

.samples-list {
  display: grid;
  gap: 1rem;
}

.empty-state {
  text-align: center;
  padding: 3rem;
  color: #718096;
}

.sample-card {
  background: white;
  padding: 1.5rem;
  border-radius: 12px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
  border: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.sample-info h3 {
  margin: 0 0 0.5rem 0;
  color: #2d3748;
  font-weight: 600;
}

.sample-info p {
  margin: 0 0 0.5rem 0;
  color: #718096;
}

.sample-summary {
  font-size: 0.9rem;
  line-height: 1.4;
  max-width: 400px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sample-metadata {
  display: flex;
  gap: 0.5rem;
  margin: 0.5rem 0;
  flex-wrap: wrap;
}

.metadata-tag {
  background: #e2e8f0;
  color: #4a5568;
  padding: 0.2rem 0.5rem;
  border-radius: 12px;
  font-size: 0.8rem;
  font-weight: 500;
}

.status {
  padding: 0.25rem 0.75rem;
  border-radius: 20px;
  font-size: 0.8rem;
  font-weight: 500;
}

.status.pending {
  background: #fef5e7;
  color: #d69e2e;
}

.status.processing {
  background: #e6fffa;
  color: #38b2ac;
}

.status.completed {
  background: #f0fff4;
  color: #38a169;
}

.status.error {
  background: #fed7d7;
  color: #e53e3e;
}

.remove-btn {
  background: #fed7d7;
  color: #e53e3e;
  border: none;
  padding: 0.5rem 1rem;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.9rem;
  transition: background-color 0.3s ease;
}

.remove-btn:hover {
  background: #feb2b2;
}

/* Analysis Tab */
.analysis-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 1.5rem;
}

.analysis-card {
  background: white;
  padding: 2rem;
  border-radius: 12px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
  border: 1px solid #e2e8f0;
  text-align: center;
}

.analysis-card h3 {
  margin: 0 0 1rem 0;
  color: #2d3748;
  font-weight: 600;
}

.analysis-card p {
  margin: 0 0 1.5rem 0;
  color: #718096;
}

.analysis-btn {
  background: #48bb78;
  color: white;
  border: none;
  padding: 0.75rem 1.5rem;
  border-radius: 8px;
  cursor: pointer;
  font-weight: 500;
  transition: background-color 0.3s ease;
  width: 100%;
}

.analysis-btn:hover:not(:disabled) {
  background: #38a169;
}

.analysis-btn:disabled {
  background: #cbd5e0;
  cursor: not-allowed;
}

/* Error and Loading States */
.error-message {
  background: #fed7d7;
  color: #e53e3e;
  padding: 1rem;
  border-radius: 8px;
  margin-bottom: 1rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.retry-btn {
  background: #e53e3e;
  color: white;
  border: none;
  padding: 0.5rem 1rem;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.9rem;
}

.retry-btn:hover {
  background: #c53030;
}

.loading-message {
  text-align: center;
  padding: 2rem;
  color: #718096;
  font-style: italic;
}

/* Action Buttons */
.action-btn {
  border: none;
  padding: 0.5rem 1rem;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.9rem;
  margin-right: 0.5rem;
  transition: background-color 0.3s ease;
}

.download-btn {
  background: #3182ce;
  color: white;
}

.download-btn:hover:not(:disabled) {
  background: #2c5aa0;
}

.count-btn {
  background: #38a169;
  color: white;
}

.count-btn:hover:not(:disabled) {
  background: #2f855a;
}

.preprocess-btn {
  background: #d69e2e;
  color: white;
}

.preprocess-btn:hover:not(:disabled) {
  background: #b7791f;
}

.action-btn:disabled {
  background: #cbd5e0;
  cursor: not-allowed;
  opacity: 0.6;
}

/* Updated sample card actions */
.sample-card .sample-actions {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  flex-wrap: wrap;
}

/* Status indicators */
.status.downloaded {
  background: #bee3f8;
  color: #2b6cb0;
}

.status.running {
  background: #fbb6ce;
  color: #b83280;
  animation: pulse 2s infinite;
}

.status.adding {
  background: #fef5e7;
  color: #d69e2e;
  animation: pulse 2s infinite;
}

.status.downloading {
  background: #bee3f8;
  color: #2b6cb0;
  animation: pulse 2s infinite;
}

.status.counting {
  background: #c6f6d5;
  color: #2f855a;
  animation: pulse 2s infinite;
}

.status.preprocessing {
  background: #fef5e7;
  color: #d69e2e;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.7;
  }
}

/* Log Window */
.logs-btn {
  background: rgba(255, 255, 255, 0.2) !important;
  position: relative;
}

.logs-btn.active {
  background: rgba(255, 255, 255, 0.4) !important;
}

.log-window {
  position: fixed;
  bottom: 20px;
  right: 20px;
  width: 400px;
  max-height: 300px;
  background: white;
  border-radius: 12px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
  border: 1px solid #e2e8f0;
  z-index: 1000;
  display: flex;
  flex-direction: column;
}

.log-header {
  padding: 1rem;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
  border-radius: 12px 12px 0 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.log-header h3 {
  margin: 0;
  font-size: 1rem;
  color: #2d3748;
  font-weight: 600;
}

.log-controls {
  display: flex;
  gap: 0.5rem;
}

.clear-btn {
  background: #e2e8f0;
  color: #4a5568;
  border: none;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.8rem;
  transition: background-color 0.3s ease;
}

.clear-btn:hover {
  background: #cbd5e0;
}

.close-btn {
  background: #fed7d7;
  color: #e53e3e;
  border: none;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.8rem;
  font-weight: bold;
  transition: background-color 0.3s ease;
}

.close-btn:hover {
  background: #feb2b2;
}

.log-content {
  flex: 1;
  overflow-y: auto;
  padding: 0.5rem;
  max-height: 200px;
}

.log-empty {
  text-align: center;
  color: #718096;
  font-style: italic;
  padding: 2rem 1rem;
}

.log-entry {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.5rem;
  border-radius: 6px;
  margin-bottom: 0.25rem;
  font-size: 0.9rem;
  line-height: 1.4;
}

.log-entry.info {
  background: #f0f9ff;
  border-left: 3px solid #3b82f6;
}

.log-entry.success {
  background: #f0fff4;
  border-left: 3px solid #10b981;
}

.log-entry.error {
  background: #fef2f2;
  border-left: 3px solid #ef4444;
}

.log-timestamp {
  color: #6b7280;
  font-size: 0.8rem;
  min-width: 60px;
  font-family: monospace;
}

.log-message {
  flex: 1;
  color: #374151;
}

/* Responsive Design */
@media (max-width: 768px) {
  .log-window {
    bottom: 10px;
    right: 10px;
    left: 10px;
    width: auto;
  }
  .samples-header {
    flex-direction: column;
    align-items: stretch;
  }
  
  .sample-actions {
    flex-direction: column;
  }
  
  .sample-input {
    min-width: 100%;
  }
  
  .sample-card {
    flex-direction: column;
    align-items: stretch;
    gap: 1rem;
  }
  
  .sample-card .sample-actions {
    justify-content: flex-start;
  }
}
</style>
