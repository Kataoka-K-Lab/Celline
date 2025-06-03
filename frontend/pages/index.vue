<template>
  <div class="container">
    <div class="hero">
      <h1>Celline Interactive</h1>
      <p>Welcome to Celline's interactive web interface</p>
    </div>
    
    <div class="main-content">
      <div class="card">
        <h2>Project Overview</h2>
        <p>Manage your single-cell RNA-seq analysis projects</p>
      </div>
      
      <div class="card">
        <h2>Sample Management</h2>
        <p>Add and manage sample data from various databases</p>
      </div>
      
      <div class="card">
        <h2>Analysis Tools</h2>
        <p>Run preprocessing, integration, and analysis workflows</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.container {
  padding: 2rem;
  max-width: 1200px;
  margin: 0 auto;
}

.hero {
  text-align: center;
  margin-bottom: 3rem;
}

.hero h1 {
  font-size: 2.5rem;
  margin-bottom: 1rem;
  color: #2c3e50;
}

.hero p {
  font-size: 1.2rem;
  color: #7f8c8d;
}

.main-content {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 2rem;
}

.card {
  background: white;
  border-radius: 8px;
  padding: 1.5rem;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
  border: 1px solid #e1e8ed;
}

.card h2 {
  margin-bottom: 1rem;
  color: #2c3e50;
}

.card p {
  color: #7f8c8d;
  line-height: 1.6;
}
</style>