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
        </nav>
      </div>
    </header>

    <!-- Main Content -->
    <main class="main-content">
      <div class="container">
        <!-- Overview Tab -->
        <div v-if="activeTab === 'overview'" class="tab-content">
          <div class="welcome-section">
            <h2>Welcome to Celline</h2>
            <p>Manage your single-cell RNA-seq analysis projects with ease.</p>
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
                placeholder="Enter sample ID (e.g., GSE123456)"
                class="sample-input"
                @keyup.enter="addSample"
              >
              <button @click="addSample" class="add-btn" :disabled="!newSampleId">
                Add Sample
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
                <p v-if="sample.title">{{ sample.title }}</p>
                <span :class="['status', sample.status]">{{ sample.status }}</span>
              </div>
              <div class="sample-actions">
                <button @click="removeSample(sample.id)" class="remove-btn">
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
  </div>
</template>

<script lang="ts">
import { defineComponent, ref, reactive } from "vue";

interface Sample {
  id: string;
  title?: string;
  status: 'pending' | 'processing' | 'completed' | 'error';
  addedAt: Date;
}

export default defineComponent({
  name: 'CellineApp',
  setup() {
    const activeTab = ref('overview');
    const newSampleId = ref('');
    const samples = reactive<Sample[]>([
      {
        id: 'GSE123456',
        title: 'Example dataset',
        status: 'completed',
        addedAt: new Date()
      }
    ]);

    const addSample = () => {
      if (!newSampleId.value.trim()) return;
      
      const sample: Sample = {
        id: newSampleId.value.trim(),
        status: 'pending',
        addedAt: new Date()
      };
      
      samples.push(sample);
      newSampleId.value = '';
      
      // TODO: Call Celline API to actually add the sample
      console.log('Adding sample:', sample.id);
    };

    const removeSample = (sampleId: string) => {
      const index = samples.findIndex(s => s.id === sampleId);
      if (index > -1) {
        samples.splice(index, 1);
        // TODO: Call Celline API to remove the sample
        console.log('Removing sample:', sampleId);
      }
    };

    return {
      activeTab,
      newSampleId,
      samples,
      addSample,
      removeSample
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

/* Responsive Design */
@media (max-width: 768px) {
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
}
</style>
