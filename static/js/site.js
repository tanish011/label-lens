document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('form.search-box').forEach(form=>form.addEventListener('submit',e=>{
    const input=form.querySelector('input[name="q"]');
    if(input&&!input.value.trim()){
      e.preventDefault();input.focus();input.setCustomValidity('Enter a product, brand or barcode to search.');input.reportValidity();
      input.addEventListener('input',()=>input.setCustomValidity(''),{once:true});
    }
  }));

  const compareForm=document.getElementById('compare-picker');
  if(compareForm){
    const datalist=document.getElementById('product-options');
    const allOptions=Array.from(datalist.options).map(option=>option.cloneNode(true));
    const category=document.getElementById('product-category');
    const filterOptions=()=>{const selected=category.value;datalist.replaceChildren(...allOptions.filter(option=>!selected||option.dataset.categories.split('|').includes(selected)));};
    category.addEventListener('change',()=>{['pick-a','pick-b'].forEach(id=>{document.getElementById(id).value='';document.getElementById(id==='pick-a'?'barcode-a':'barcode-b').value='';});filterOptions();});
    filterOptions();
    const pairs=[['pick-a','barcode-a'],['pick-b','barcode-b']];
    const resolve=([inputId,hiddenId])=>{
      const input=document.getElementById(inputId), hidden=document.getElementById(hiddenId);
      const match=Array.from(datalist.options).find(option=>option.value===input.value);
      hidden.value=match?match.dataset.barcode:'';
      if(input.value) input.setCustomValidity(match?'':'Choose a product from the suggestions.');
      else input.setCustomValidity('');
      return hidden.value;
    };
    pairs.forEach(pair=>{
      const input=document.getElementById(pair[0]);
      input.addEventListener('input',()=>resolve(pair));
      input.addEventListener('change',()=>resolve(pair));
    });
    compareForm.addEventListener('submit',event=>{
      const [first,second]=pairs.map(resolve);
      if(!first||!second){event.preventDefault();pairs.map(pair=>document.getElementById(pair[0])).find(input=>!input.value||!document.getElementById(input.id==='pick-a'?'barcode-a':'barcode-b').value)?.reportValidity();return;}
      if(first===second){event.preventDefault();const input=document.getElementById('pick-b');input.setCustomValidity('Choose a different product for the comparison.');input.reportValidity();input.addEventListener('input',()=>input.setCustomValidity(''),{once:true});}
    });
  }
});